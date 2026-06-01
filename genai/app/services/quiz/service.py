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

TOTAL_QUESTIONS: int = 10          # 7 지식 + 3 성향
KNOWLEDGE_QUESTIONS: int = 7

_DIFFICULTY_LABELS = {1: "입문", 2: "기초", 3: "중급", 4: "고급", 5: "전문가"}

# ── 고정 성향 문제 3개 ─────────────────────────────────────────────────────────
_PREFERENCE_QUESTIONS = [
    {
        "question_number_offset": 1,  # Q8
        "key": "Q8",
        "question_text": "주식 시장에서 예상치 못한 큰 하락이 발생했을 때, 당신은 어떻게 하겠습니까?",
        "choices": {
            "A": "지금이 기회다 — 추가 매수한다",
            "B": "상황을 지켜보며 기다린다",
            "C": "리스크를 줄이기 위해 일부 매도한다",
            "D": "손실 최소화를 위해 대부분 매도한다",
            "E": "아직 투자 경험이 없어 잘 모르겠다",
        },
    },
    {
        "question_number_offset": 2,  # Q9
        "key": "Q9",
        "question_text": "투자할 종목을 고를 때 가장 먼저 보는 것은 무엇인가요?",
        "choices": {
            "A": "기업의 실적, 재무제표, 내재가치",
            "B": "최근 뉴스, 이슈, 시장 분위기",
            "C": "주가 차트와 기술적 지표",
            "D": "전문가 추천이나 커뮤니티 의견",
            "E": "아직 스스로 판단하기 어렵다",
        },
    },
    {
        "question_number_offset": 3,  # Q10
        "key": "Q10",
        "question_text": "나에게 가장 잘 맞는 투자 스타일은 무엇인가요?",
        "choices": {
            "A": "단기 수익 — 빠르게 사고 팔며 수익 실현",
            "B": "성장 투자 — 몇 달~1년 보유하며 성장 기대",
            "C": "장기 투자 — 5년 이상 보유하며 복리 효과 기대",
            "D": "인컴 투자 — 배당금·이자 등 정기 수익 선호",
            "E": "아직 어떤 스타일이 맞는지 모르겠다",
        },
    },
]

# ── 성향 점수표 ────────────────────────────────────────────────────────────────
_TENDENCY_WEIGHTS = {
    "Q8": {
        "A": {"공격성장형": 2, "모멘텀형": 1},
        "B": {"가치투자형": 2, "안정추구형": 1},
        "C": {"안정추구형": 2},
        "D": {"안정추구형": 1},
        "E": {"탐색형": 3},
    },
    "Q9": {
        "A": {"가치투자형": 3},
        "B": {"모멘텀형": 2, "공격성장형": 1},
        "C": {"모멘텀형": 3},
        "D": {"안정추구형": 2},
        "E": {"탐색형": 3},
    },
    "Q10": {
        "A": {"모멘텀형": 3},
        "B": {"공격성장형": 2},
        "C": {"가치투자형": 2, "안정추구형": 1},
        "D": {"인컴형": 3},
        "E": {"탐색형": 3},
    },
}

_TENDENCY_INFO = {
    "공격성장형": (
        "공격성장형",
        "성장 가능성이 높은 자산에 과감하게 투자하는 성향입니다.",
        "성장주, 기술주, 신흥시장, 섹터 트렌드 뉴스를 중심으로 보여드립니다.",
    ),
    "가치투자형": (
        "가치투자형",
        "기업의 내재가치를 분석해 저평가 종목을 찾는 성향입니다.",
        "기업 실적, 재무제표, 저평가 종목 분석 뉴스를 중심으로 보여드립니다.",
    ),
    "모멘텀형": (
        "모멘텀형",
        "시장 흐름과 이슈를 빠르게 포착해 움직이는 성향입니다.",
        "시장 이슈, 핫 섹터, 단기 시황 뉴스를 중심으로 보여드립니다.",
    ),
    "안정추구형": (
        "안정추구형",
        "손실 방어와 안정적 수익을 최우선으로 하는 성향입니다.",
        "배당주, 채권, 방어적 업종, 리스크 관리 뉴스를 중심으로 보여드립니다.",
    ),
    "인컴형": (
        "인컴형",
        "배당금·이자 등 정기적인 현금 흐름을 선호하는 성향입니다.",
        "고배당주, 리츠, 채권 수익률, 배당 캘린더 뉴스를 중심으로 보여드립니다.",
    ),
    "탐색형": (
        "탐색형",
        "아직 투자 스타일을 찾아가는 단계입니다.",
        "기초 개념 설명이 포함된 다양한 섹터 입문 뉴스를 보여드립니다.",
    ),
}

# ── 지식 문제 프롬프트 ──────────────────────────────────────────────────────────
_KNOWLEDGE_SYSTEM_PROMPT = """당신은 금융 투자 교육 전문가입니다. 객관식 금융 지식 문제를 생성합니다.

【필수 조건】
1. 반드시 사실에 기반한 하나의 명확한 정답이 있어야 합니다
2. 오답 선택지도 그럴듯하지만 틀린 내용이어야 합니다
3. 금융 지식을 테스트하는 문제여야 합니다 (개념 정의, 계산, 인과관계 등)

【절대 금지 유형 — 이런 문제는 만들지 마세요】
- "당신은 어떻게 하겠습니까?" (행동 선택)
- "가장 먼저 알아야 할 것은?" (순서 판단)
- "가장 중요한 것은?" (중요도 판단)
- "투자자들은 주로 어떻게 느끼나요?" (심리 추측)
- "어떤 방법이 좋을까요?" (선호도)
→ 이런 문제들은 정답이 없어서 출제 불가

【좋은 문제 예시】
- "PER(주가수익비율)을 구하는 공식은?" → 계산식 정의
- "기준금리가 오르면 채권 가격은?" → 인과관계
- "코스피200 지수에 포함된 종목 수는?" → 사실 확인
- "RSI가 70을 초과할 때 나타내는 신호는?" → 지표 해석
- "EPS(주당순이익)를 계산할 때 필요한 값은?" → 개념 정의

【출제 카테고리】
- 기업재무: PER, PBR, ROE, EPS, 부채비율, 배당수익률, 현금흐름
- 시장구조: 코스피/코스닥/나스닥, 시가총액, 거래량, 호가
- 경제지표: 기준금리, GDP, 인플레이션, 환율, 실업률
- 투자상품: ETF, 채권, 선물, 옵션, 펀드 구조
- 기술적분석: RSI, MACD, 이동평균선, 볼린저밴드
- 리스크지표: 베타계수, 표준편차, 샤프지수, VaR

【난이도 기준】
- 1 (입문): 주식이란, 시장 종류, 기초 용어 정의
- 2 (기초): PER 계산, 배당수익률, 금리와 채권 관계
- 3 (중급): EBITDA, 베타계수, MACD 해석
- 4 (고급): DCF 모델, 옵션 그릭스, 포트폴리오 분산
- 5 (전문가): 블랙숄즈, 차익거래, 파생상품 구조

반드시 다음 JSON 형식으로만 응답하세요. JSON 외 텍스트 금지:
{
  "question_text": "문제 (구체적이고 정답이 명확한 사실 문제)",
  "choices": {
    "A": "선택지 A",
    "B": "선택지 B",
    "C": "선택지 C",
    "D": "선택지 D",
    "E": "잘 모르겠다"
  },
  "correct_answer": "A",
  "explanation": "정답 설명 (왜 맞는지 2~3문장)",
  "topic": "구체적 주제 키워드 (예: PER계산, RSI신호, 채권금리관계)",
  "category": "카테고리명"
}

E번은 항상 "잘 모르겠다"로 고정. correct_answer는 절대 E 불가."""


def _shuffle_choices(choices: dict, correct_answer: str) -> tuple[dict, str]:
    """A~D 선택지를 랜덤으로 섞고, 정답 키를 새 위치로 업데이트."""
    import random
    keys = ["A", "B", "C", "D"]
    texts = [choices[k] for k in keys]
    random.shuffle(texts)
    shuffled = {k: t for k, t in zip(keys, texts)}
    shuffled["E"] = "잘 모르겠다"
    original_text = choices[correct_answer]
    new_correct = next(k for k, t in shuffled.items() if t == original_text)
    return shuffled, new_correct


_QUESTION_TYPES = [
    "개념 계산 (예: PER이 20이고 EPS가 5달러일 때 주가는?)",
    "인과관계 (예: 기준금리 상승 시 채권 가격 변화는?)",
    "지표 해석 (예: RSI가 80일 때 의미하는 신호는?)",
    "차이점 비교 (예: ETF와 일반 펀드의 가장 큰 차이는?)",
    "사실 확인 (예: 코스피200에 포함된 종목 수는?)",
]

def _build_knowledge_prompt(difficulty: float, used_topics: list[str]) -> str:
    import random
    level = max(1, min(5, round(difficulty)))
    label = _DIFFICULTY_LABELS[level]
    question_type = random.choice(_QUESTION_TYPES)

    if used_topics:
        prev_str = "\n".join(f"- {q}" for q in used_topics[:20])
        dedup_instruction = f"""
아래는 이미 출제된 문제들입니다. 이와 동일하거나 매우 유사한 내용을 묻는 문제는 절대 생성하지 마세요:
{prev_str}
"""
    else:
        dedup_instruction = ""

    return (
        f"난이도 {level}/5 ({label}) 수준의 금융 지식 문제 1개를 생성해주세요.\n"
        f"문제 유형: {question_type}\n"
        f"{dedup_instruction}"
        f"완전히 다른 개념과 다른 유형의 문제를 출제하세요."
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
    else:
        return max(1.0, round(current - 0.3, 2))


def _compute_final_level(difficulty: float) -> int:
    return max(1, min(5, round(difficulty)))


def _compute_tendency_from_preferences(session_id: str, settings) -> dict:
    with connect_postgres(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT topic, user_answer
                FROM quiz_questions
                WHERE session_id = %s AND question_type = 'preference' AND user_answer IS NOT NULL
                ORDER BY question_number ASC
                """,
                (session_id,),
            )
            rows = cur.fetchall()

    scores: dict[str, int] = {}
    for row in rows:
        q_key = row["topic"]        # Q8, Q9, Q10
        answer = row["user_answer"] # A~E
        weights = _TENDENCY_WEIGHTS.get(q_key, {}).get(answer, {})
        for tendency, weight in weights.items():
            scores[tendency] = scores.get(tendency, 0) + weight

    if not scores:
        best = "탐색형"
    else:
        best = max(scores, key=lambda k: scores[k])

    name, description, news_hint = _TENDENCY_INFO.get(best, _TENDENCY_INFO["탐색형"])
    return {
        "tendency": name,
        "tendency_description": description,
        "news_hint": news_hint,
    }


# ── Public API ─────────────────────────────────────────────────────────────────

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
                VALUES (%s, %s, 1.0, 0, 0, 'in_progress', %s, %s)
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
        "knowledge_questions": KNOWLEDGE_QUESTIONS,
        "final_level": row["final_level"],
    }


def get_session(session_id: str) -> dict | None:
    settings = get_settings()
    with connect_postgres(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, current_difficulty, questions_asked, correct_count, status, final_level FROM quiz_sessions WHERE id = %s",
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
        "knowledge_questions": KNOWLEDGE_QUESTIONS,
        "final_level": row["final_level"],
    }


def generate_next_question(session_id: str) -> dict:
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

    question_number = session["questions_asked"] + 1

    # Q8~Q10: 고정 성향 문제
    if question_number > KNOWLEDGE_QUESTIONS:
        return _get_preference_question(session_id, question_number, settings)

    # Q1~Q7: Gemini 지식 문제
    return _get_knowledge_question(session_id, question_number, session["current_difficulty"], settings)


def _get_knowledge_question(session_id: str, question_number: int, difficulty: float, settings) -> dict:
    from app.services.gemini.client import gemini_generate_content
    from psycopg.types.json import Jsonb

    with connect_postgres(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            # 현재 세션 + 같은 user_id의 최근 40개 질문 텍스트 수집
            cur.execute("""
                SELECT qq.question_text
                FROM quiz_questions qq
                JOIN quiz_sessions qs ON qs.id = qq.session_id
                WHERE qq.question_type = 'multiple_choice'
                  AND (
                    qq.session_id = %s
                    OR (
                      qs.user_id = (SELECT user_id FROM quiz_sessions WHERE id = %s)
                      AND qs.user_id IS NOT NULL
                    )
                  )
                ORDER BY qq.created_at DESC
                LIMIT 40
            """, (session_id, session_id))
            # 앞 30자만 추출해서 전달 (Gemini가 유사 문제 피하도록)
            used_topics = [r["question_text"][:30] for r in cur.fetchall() if r["question_text"]]

    raw = gemini_generate_content(
        system_prompt=_KNOWLEDGE_SYSTEM_PROMPT,
        user_prompt=_build_knowledge_prompt(difficulty, used_topics),
        model=settings.gemini_summary_model,
        temperature=0.9,
        request_label="quiz_knowledge",
    )
    parsed = _parse_gemini_response(raw)

    choices = parsed["choices"]
    if not isinstance(choices, dict) or not {"A", "B", "C", "D"}.issubset(choices.keys()):
        raise RuntimeError("Gemini가 올바른 선택지 형식을 반환하지 않았습니다.")

    correct_answer = parsed["correct_answer"].strip().upper()
    if correct_answer not in {"A", "B", "C", "D"}:
        raise RuntimeError("Gemini가 올바른 정답을 반환하지 않았습니다.")

    # 정답 위치 편향 제거 (LLM이 A에 정답을 몰아주는 경향)
    choices, correct_answer = _shuffle_choices(choices, correct_answer)

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
                (question_id, session_id, question_number, parsed["question_text"],
                 Jsonb(choices), correct_answer, parsed.get("explanation", ""),
                 difficulty, topic_stored, now),
            )

    return {
        "question_id": question_id,
        "question_number": question_number,
        "question_type": "knowledge",
        "question_text": parsed["question_text"],
        "choices": choices,
        "difficulty": difficulty,
    }


def _get_preference_question(session_id: str, question_number: int, settings) -> dict:
    from psycopg.types.json import Jsonb

    offset = question_number - KNOWLEDGE_QUESTIONS - 1  # 0,1,2
    pq = _PREFERENCE_QUESTIONS[offset]

    question_id = str(uuid4())
    now = datetime.now(timezone.utc)
    with connect_postgres(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO quiz_questions
                    (id, session_id, question_number, question_text, question_type,
                     choices, correct_answer, explanation, difficulty, topic, created_at)
                VALUES (%s, %s, %s, %s, 'preference', %s, 'PREFERENCE', '', NULL, %s, %s)
                """,
                (question_id, session_id, question_number, pq["question_text"],
                 Jsonb(pq["choices"]), pq["key"], now),
            )

    return {
        "question_id": question_id,
        "question_number": question_number,
        "question_type": "preference",
        "question_text": pq["question_text"],
        "choices": pq["choices"],
        "difficulty": None,
    }


def submit_answer(session_id: str, question_id: str, answer: str) -> dict:
    settings = get_settings()

    with connect_postgres(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT correct_answer, explanation, is_correct, question_type FROM quiz_questions WHERE id = %s AND session_id = %s",
                (question_id, session_id),
            )
            question = cur.fetchone()
            if question is None:
                raise ValueError("문항을 찾을 수 없습니다.")
            if question["is_correct"] is not None or (
                question["question_type"] == "preference" and question["explanation"] == "" and
                _already_answered(cur, question_id)
            ):
                raise ValueError("이미 답변한 문항입니다.")

            is_preference = question["question_type"] == "preference"
            is_모름 = answer == "E" and not is_preference
            is_correct = False if is_preference or is_모름 else (answer == question["correct_answer"])

            if is_preference:
                cur.execute(
                    "UPDATE quiz_questions SET user_answer = %s WHERE id = %s",
                    (answer, question_id),
                )
            else:
                cur.execute(
                    "UPDATE quiz_questions SET user_answer = %s, is_correct = %s WHERE id = %s",
                    (answer, is_correct, question_id),
                )

            cur.execute(
                "SELECT current_difficulty, questions_asked, correct_count FROM quiz_sessions WHERE id = %s",
                (session_id,),
            )
            session = cur.fetchone()
            new_questions_asked = session["questions_asked"] + 1

            if is_preference:
                new_difficulty = session["current_difficulty"]
                new_correct_count = session["correct_count"]
            else:
                new_difficulty = _adjust_difficulty(session["current_difficulty"], is_correct, is_모름)
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
                    "UPDATE quiz_sessions SET current_difficulty = %s, questions_asked = %s, correct_count = %s WHERE id = %s",
                    (new_difficulty, new_questions_asked, new_correct_count, session_id),
                )
                session_status = "in_progress"

    result = {
        "is_correct": is_correct,
        "is_모름": is_모름,
        "is_preference": is_preference,
        "correct_answer": question["correct_answer"] if not is_preference else None,
        "explanation": question["explanation"] if not is_preference else None,
        "session_status": session_status,
        "questions_asked": new_questions_asked,
        "correct_count": new_correct_count,
        "total_questions": TOTAL_QUESTIONS,
        "knowledge_questions": KNOWLEDGE_QUESTIONS,
        "final_level": final_level,
        "tendency": None,
        "tendency_description": None,
        "news_hint": None,
    }

    if session_status == "completed":
        tendency_info = _compute_tendency_from_preferences(session_id, settings)
        result.update(tendency_info)

    return result


def _already_answered(cur, question_id: str) -> bool:
    cur.execute("SELECT user_answer FROM quiz_questions WHERE id = %s", (question_id,))
    row = cur.fetchone()
    return row is not None and row["user_answer"] is not None
