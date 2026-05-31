from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from uuid import uuid4

from app.core import get_settings
from app.db.postgres import connect_postgres

logger = logging.getLogger(__name__)

TOTAL_QUESTIONS: int = int(os.getenv("GENAI_QUIZ_TOTAL_QUESTIONS", "7"))

_DIFFICULTY_LABELS = {1: "입문", 2: "기초", 3: "중급", 4: "고급", 5: "전문가"}

# 카테고리 → 투자 성향 설명
_TENDENCY_MAP = {
    "기업가치": ("가치투자형", "기업의 내재가치를 분석하는 성향입니다. 재무제표와 기업 분석에 강점이 있으며 저평가 종목 발굴에 관심이 높습니다."),
    "시장트렌드": ("모멘텀 투자형", "시장의 흐름과 트렌드를 읽는 성향입니다. 타이밍과 섹터 로테이션에 민감하게 반응합니다."),
    "경제지표": ("거시경제형", "금리·환율·GDP 등 거시경제 지표를 기반으로 판단하는 성향입니다. 큰 그림에서 투자 방향을 잡습니다."),
    "투자전략": ("전략형", "체계적인 포트폴리오와 분산투자를 중시하는 성향입니다. 장기적 관점에서 자산 배분에 강점이 있습니다."),
    "투자심리": ("역발상 투자형", "시장 심리와 군중 행동을 이해하는 성향입니다. 공포와 탐욕을 역이용하는 역발상 투자에 강합니다."),
    "리스크관리": ("안정추구형", "손실 방어와 리스크 관리를 최우선으로 하는 성향입니다. 안정적인 수익을 선호합니다."),
    "글로벌시장": ("글로벌 투자형", "해외 시장과 환율 변동에 주목하는 성향입니다. 글로벌 분산투자에 관심이 높습니다."),
    "파생상품": ("전문투자형", "옵션·선물 등 고급 투자 도구에 관심이 높은 성향입니다. 레버리지와 헤징 전략을 활용합니다."),
    "균형형": ("종합균형형", "특정 분야에 치우치지 않고 폭넓게 접근하는 성향입니다. 다양한 투자 방식을 균형 있게 이해합니다."),
}

_SYSTEM_PROMPT = """당신은 금융 투자 교육 전문가입니다. 주어진 난이도와 카테고리에 맞는 금융 퀴즈 문제를 생성합니다.

문제 유형: 객관식 5지선다 (A, B, C, D + E번은 반드시 "잘 모르겠다"로 고정)
언어: 한국어

문제 카테고리 — 아래 카테고리를 골고루 출제하세요:
- 시장트렌드: 불/베어마켓, 금리 사이클, 섹터 로테이션, 시장 사이클, 경기 침체
- 투자심리: 공포탐욕 지수, 군중심리, 손실회피, 행동경제학, 버블과 패닉
- 경제지표: GDP, 인플레이션, 기준금리, 환율, 실업률, 소비자물가지수
- 기업가치: PER, PBR, ROE, EPS, 배당수익률, 현금흐름, 부채비율
- 투자전략: 분산투자, 가치투자, 성장주투자, 배당투자, ETF, 적립식 투자
- 리스크관리: 헤징, 포트폴리오 비중, 손절매, 변동성, 베타계수
- 글로벌시장: 미국/중국 시장, 신흥시장, 환율 영향, 글로벌 공급망

난이도 기준:
- 1 (입문): 주식이란, 분산투자 개념, 기초 금융 용어
- 2 (기초): PER, 배당수익률, 불/베어마켓, 기본 경제 지표 읽기
- 3 (중급): EBITDA, 베타계수, 금리와 주가 관계, 섹터 분석
- 4 (고급): DCF 모델, 옵션 전략, 포트폴리오 최적화
- 5 (전문가): 블랙숄즈, 차익거래, 고급 파생상품

반드시 다음 JSON 형식으로만 응답하세요. JSON 외 텍스트는 절대 포함하지 마세요:
{
  "question_text": "문제 내용",
  "choices": {
    "A": "선택지 A",
    "B": "선택지 B",
    "C": "선택지 C",
    "D": "선택지 D",
    "E": "잘 모르겠다"
  },
  "correct_answer": "A",
  "explanation": "정답 설명 (2~3문장, 핵심 개념 포함)",
  "topic": "주제 키워드 (예: PER, 금리, 손절매)",
  "category": "카테고리명 (시장트렌드/투자심리/경제지표/기업가치/투자전략/리스크관리/글로벌시장 중 하나)"
}

E번은 항상 "잘 모르겠다"로 고정하며, correct_answer는 절대 E가 될 수 없습니다."""


def _build_user_prompt(difficulty: float, used_topics: list[str]) -> str:
    level = max(1, min(5, round(difficulty)))
    label = _DIFFICULTY_LABELS[level]
    topics_str = ", ".join(used_topics[-6:]) if used_topics else "없음"
    return (
        f"난이도 {level}/5 ({label}) 수준의 금융 퀴즈 문제 1개를 생성해주세요.\n"
        f"이미 출제된 주제 (중복 금지): {topics_str}\n"
        f"다양한 카테고리에서 골고루 출제해주세요."
    )


def _parse_gemini_response(raw_text: str) -> dict:
    text = raw_text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if match:
        text = match.group(1).strip()
    return json.loads(text)


def _adjust_difficulty(current: float, is_correct: bool, is_모름: bool = False) -> float:
    if is_correct:
        return min(5.0, round(current + 0.4, 2))
    elif is_모름:
        return max(1.0, round(current - 0.15, 2))  # 모름은 소폭 하향
    else:
        return max(1.0, round(current - 0.3, 2))


def _compute_final_level(difficulty: float) -> int:
    return max(1, min(5, round(difficulty)))


def _compute_tendency(session_id: str, settings) -> dict:
    """카테고리별 정답률 기반으로 투자 성향 분석."""
    with connect_postgres(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT topic, is_correct, user_answer
                FROM quiz_questions
                WHERE session_id = %s AND is_correct IS NOT NULL
                """,
                (session_id,),
            )
            rows = cur.fetchall()

    category_stats: dict[str, dict] = {}
    for row in rows:
        topic = row["topic"] or ""
        category = topic.split("|")[0] if "|" in topic else "기타"
        if category not in category_stats:
            category_stats[category] = {"correct": 0, "wrong": 0, "모름": 0}
        if row["user_answer"] == "E":
            category_stats[category]["모름"] += 1
        elif row["is_correct"]:
            category_stats[category]["correct"] += 1
        else:
            category_stats[category]["wrong"] += 1

    if not category_stats:
        tendency_key = "균형형"
    else:
        # 정답이 가장 많은 카테고리를 주요 성향으로
        best_category = max(
            category_stats.keys(),
            key=lambda c: category_stats[c]["correct"]
        )
        # 모든 카테고리에 정답이 0이면 균형형
        if category_stats[best_category]["correct"] == 0:
            tendency_key = "균형형"
        elif len([c for c in category_stats if category_stats[c]["correct"] > 0]) >= 3:
            tendency_key = "균형형"
        else:
            tendency_key = best_category if best_category in _TENDENCY_MAP else "균형형"

    label, description = _TENDENCY_MAP.get(tendency_key, _TENDENCY_MAP["균형형"])
    return {
        "tendency": label,
        "tendency_description": description,
        "category_stats": {
            c: s for c, s in category_stats.items() if c != "기타"
        },
    }


def create_session(user_id: str | None) -> dict:
    settings = get_settings()
    if settings.database_backend != "postgres":
        raise RuntimeError("퀴즈 기능은 Postgres 백엔드에서만 사용 가능합니다.")

    session_id = str(uuid4())
    now = datetime.now(timezone.utc)
    with connect_postgres(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO quiz_sessions
                    (id, user_id, current_difficulty, questions_asked, correct_count, status, started_at, created_at)
                VALUES (%s, %s, 2.0, 0, 0, 'in_progress', %s, %s)
                RETURNING id, current_difficulty, questions_asked, correct_count, status, final_level
                """,
                (session_id, user_id, now, now),
            )
            row = cur.fetchone()
    return {
        "session_id": str(row["id"]),
        "status": row["status"],
        "current_difficulty": row["current_difficulty"],
        "questions_asked": row["questions_asked"],
        "correct_count": row["correct_count"],
        "total_questions": TOTAL_QUESTIONS,
        "final_level": row["final_level"],
    }


def get_session(session_id: str) -> dict | None:
    settings = get_settings()
    with connect_postgres(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, current_difficulty, questions_asked, correct_count, status, final_level
                FROM quiz_sessions WHERE id = %s
                """,
                (session_id,),
            )
            row = cur.fetchone()
    if row is None:
        return None
    return {
        "session_id": str(row["id"]),
        "status": row["status"],
        "current_difficulty": row["current_difficulty"],
        "questions_asked": row["questions_asked"],
        "correct_count": row["correct_count"],
        "total_questions": TOTAL_QUESTIONS,
        "final_level": row["final_level"],
    }


def generate_next_question(session_id: str) -> dict:
    from app.services.gemini.client import gemini_generate_content
    from psycopg.types.json import Jsonb

    settings = get_settings()
    with connect_postgres(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT current_difficulty, questions_asked, status FROM quiz_sessions WHERE id = %s",
                (session_id,),
            )
            session = cur.fetchone()
            if session is None:
                raise ValueError("세션을 찾을 수 없습니다.")
            if session["status"] != "in_progress":
                raise ValueError("이미 완료된 세션입니다.")
            if session["questions_asked"] >= TOTAL_QUESTIONS:
                raise ValueError("모든 문제를 이미 출제했습니다.")

            cur.execute(
                "SELECT topic FROM quiz_questions WHERE session_id = %s ORDER BY question_number ASC",
                (session_id,),
            )
            used_topics = [r["topic"] for r in cur.fetchall() if r["topic"]]

    difficulty = session["current_difficulty"]
    question_number = session["questions_asked"] + 1

    raw = gemini_generate_content(
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=_build_user_prompt(difficulty, used_topics),
        model=settings.gemini_summary_model,
        temperature=0.8,
        request_label="quiz_question",
    )
    parsed = _parse_gemini_response(raw)

    choices = parsed["choices"]
    if not isinstance(choices, dict) or not {"A", "B", "C", "D", "E"}.issubset(choices.keys()):
        raise RuntimeError("Gemini가 올바른 선택지 형식을 반환하지 않았습니다.")
    choices["E"] = "잘 모르겠다"  # E는 항상 고정

    correct_answer = parsed["correct_answer"].strip().upper()
    if correct_answer not in {"A", "B", "C", "D"}:
        raise RuntimeError("Gemini가 올바른 정답을 반환하지 않았습니다.")

    category = parsed.get("category", "").strip()
    topic = parsed.get("topic", "").strip()
    topic_stored = f"{category}|{topic}" if category else topic

    question_id = str(uuid4())
    now = datetime.now(timezone.utc)
    with connect_postgres(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO quiz_questions
                    (id, session_id, question_number, question_text, question_type,
                     choices, correct_answer, explanation, difficulty, topic, created_at)
                VALUES (%s, %s, %s, %s, 'multiple_choice', %s, %s, %s, %s, %s, %s)
                """,
                (
                    question_id, session_id, question_number,
                    parsed["question_text"],
                    Jsonb(choices),
                    correct_answer,
                    parsed.get("explanation", ""),
                    difficulty,
                    topic_stored,
                    now,
                ),
            )

    return {
        "question_id": question_id,
        "question_number": question_number,
        "question_text": parsed["question_text"],
        "choices": choices,
        "difficulty": difficulty,
    }


def submit_answer(session_id: str, question_id: str, answer: str) -> dict:
    settings = get_settings()
    is_모름 = answer == "E"

    with connect_postgres(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT correct_answer, explanation, is_correct FROM quiz_questions WHERE id = %s AND session_id = %s",
                (question_id, session_id),
            )
            question = cur.fetchone()
            if question is None:
                raise ValueError("문항을 찾을 수 없습니다.")
            if question["is_correct"] is not None:
                raise ValueError("이미 답변한 문항입니다.")

            is_correct = (not is_모름) and (answer == question["correct_answer"])
            cur.execute(
                "UPDATE quiz_questions SET user_answer = %s, is_correct = %s WHERE id = %s",
                (answer, is_correct, question_id),
            )

            cur.execute(
                "SELECT current_difficulty, questions_asked, correct_count FROM quiz_sessions WHERE id = %s",
                (session_id,),
            )
            session = cur.fetchone()
            new_difficulty = _adjust_difficulty(session["current_difficulty"], is_correct, is_모름)
            new_questions_asked = session["questions_asked"] + 1
            new_correct_count = session["correct_count"] + (1 if is_correct else 0)

            if new_questions_asked >= TOTAL_QUESTIONS:
                final_level = _compute_final_level(new_difficulty)
                now = datetime.now(timezone.utc)
                cur.execute(
                    """
                    UPDATE quiz_sessions
                    SET current_difficulty = %s, questions_asked = %s, correct_count = %s,
                        status = 'completed', final_level = %s, completed_at = %s
                    WHERE id = %s
                    """,
                    (new_difficulty, new_questions_asked, new_correct_count, final_level, now, session_id),
                )
                session_status = "completed"
            else:
                final_level = None
                cur.execute(
                    """
                    UPDATE quiz_sessions
                    SET current_difficulty = %s, questions_asked = %s, correct_count = %s
                    WHERE id = %s
                    """,
                    (new_difficulty, new_questions_asked, new_correct_count, session_id),
                )
                session_status = "in_progress"

    result = {
        "is_correct": is_correct,
        "is_모름": is_모름,
        "correct_answer": question["correct_answer"],
        "explanation": question["explanation"] or "",
        "session_status": session_status,
        "questions_asked": new_questions_asked,
        "correct_count": new_correct_count,
        "total_questions": TOTAL_QUESTIONS,
        "final_level": final_level,
        "tendency": None,
        "tendency_description": None,
    }

    if session_status == "completed":
        tendency_info = _compute_tendency(session_id, settings)
        result["tendency"] = tendency_info["tendency"]
        result["tendency_description"] = tendency_info["tendency_description"]

    return result
