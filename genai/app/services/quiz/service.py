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

TOTAL_QUESTIONS: int = 10           # 7 지식 + 3 성향
KNOWLEDGE_QUESTIONS: int = 7
DEEP_EXTRA_QUESTIONS: int = 5       # 심층 분석 추가 문제 수

# 5개 측정 영역 (오각형 스탯)
AREAS = ["기본개념", "마켓수급", "매크로", "펀더멘털", "리스크관리"]

# 기본 7문제에서 영역 순환 (Q1~Q7)
_AREA_CYCLE = ["기본개념", "마켓수급", "매크로", "펀더멘털", "리스크관리", "기본개념", "마켓수급"]

_DIFFICULTY_LABELS = {1: "입문", 2: "기초", 3: "중급", 4: "고급", 5: "전문가"}

# ── 고정 성향 문제 3개 ─────────────────────────────────────────────────────────
_PREFERENCE_QUESTIONS = [
    {
        "question_number_offset": 1,
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
        "question_number_offset": 2,
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
        "question_number_offset": 3,
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
    "공격성장형": ("공격성장형", "성장 가능성이 높은 자산에 과감하게 투자하는 성향입니다.", "성장주, 기술주, 신흥시장 뉴스를 중심으로 보여드립니다."),
    "가치투자형": ("가치투자형", "기업의 내재가치를 분석해 저평가 종목을 찾는 성향입니다.", "기업 실적, 재무제표, 저평가 종목 분석 뉴스를 보여드립니다."),
    "모멘텀형": ("모멘텀형", "시장 흐름과 이슈를 빠르게 포착해 움직이는 성향입니다.", "시장 이슈, 핫 섹터, 단기 시황 뉴스를 보여드립니다."),
    "안정추구형": ("안정추구형", "손실 방어와 안정적 수익을 최우선으로 하는 성향입니다.", "배당주, 채권, 방어적 업종 뉴스를 보여드립니다."),
    "인컴형": ("인컴형", "배당금·이자 등 정기적인 현금 흐름을 선호하는 성향입니다.", "고배당주, 리츠, 채권 수익률 뉴스를 보여드립니다."),
    "탐색형": ("탐색형", "아직 투자 스타일을 찾아가는 단계입니다.", "기초 개념 설명이 포함된 다양한 섹터 뉴스를 보여드립니다."),
}

# ── 지식 문제 프롬프트 ──────────────────────────────────────────────────────────
_KNOWLEDGE_SYSTEM_PROMPT = """당신은 금융 투자 교육 전문가입니다. 객관식 금융 지식 문제를 생성합니다.

【필수 조건】
1. 반드시 사실에 기반한 하나의 명확한 정답이 있어야 합니다
2. 오답 선택지도 그럴듯하지만 틀린 내용이어야 합니다
3. 오답에 "항상/무조건/절대/반드시" 같은 극단 표현을 넣어 구분력을 높이세요

【절대 금지 유형】
- "당신은 어떻게 하겠습니까?" / "가장 먼저 알아야 할 것은?" / "가장 중요한 것은?"
→ 이런 문제는 정답이 없으므로 출제 불가

【5개 측정 영역 — 반드시 지정된 영역으로 출제하세요】
- 기본개념: 주식의 의미, 주주, 분산투자, 배당, 시가총액, 거래소 구조
- 마켓수급: 수급/거래량, 가격 결정, 어닝 서프라이즈, 선반영, 기술적 신호(RSI/MACD)
- 매크로: 기준금리, GDP, 인플레이션, 환율, 금리-채권 관계, 성장주-금리 관계
- 펀더멘털: PER, PBR, ROE, EPS, 재무제표, DCF, 배당수익률 계산
- 리스크관리: 베타계수, 변동성, 포트폴리오 분산, 손절, 헤징, 샤프지수

【난이도 기준】
- 1 (입문): 상식 수준. "주식을 사면 그 회사의 무엇이 되나요?"
- 2 (기초): 뉴스 읽는 수준. "배당이란?", "시가총액 큰 기업의 의미는?"
- 3 (중급): 투자 시작 수준. "PER이 낮으면?", "금리 오르면 채권 가격은?"
- 4 (고급): 재무제표 읽는 수준. "ROE가 높은 기업의 특징은?", "베타 1.5 의미?"
- 5 (전문가): "DCF 모델에서 할인율이 높아지면?", "블랙숄즈 모델에서 변동성 증가 시?"

반드시 다음 JSON으로만 응답하세요:
{
  "question_text": "문제",
  "choices": {"A": "...", "B": "...", "C": "...", "D": "...", "E": "잘 모르겠다"},
  "correct_answer": "A",
  "explanation": "정답 설명 2~3문장",
  "topic": "구체적 키워드",
  "area": "기본개념|마켓수급|매크로|펀더멘털|리스크관리 중 하나"
}

E번은 항상 "잘 모르겠다". correct_answer는 E 불가."""


def _shuffle_choices(choices: dict, correct_answer: str) -> tuple[dict, str]:
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
    "인과관계 (예: 금리 상승 시 채권 가격 변화는?)",
    "지표 해석 (예: RSI가 80일 때 의미하는 신호는?)",
    "개념 계산 (예: PER이 20이고 EPS가 5달러일 때 주가는?)",
    "차이점 비교 (예: ETF와 일반 펀드의 가장 큰 차이는?)",
    "원인 파악 (예: 어닝 서프라이즈인데 주가가 하락하는 이유는?)",
]


def _build_knowledge_prompt(
    difficulty: float,
    target_area: str,
    used_questions: list[str],
    last_correct: bool | None = None,
) -> str:
    import random
    level = max(1, min(5, round(difficulty)))
    label = _DIFFICULTY_LABELS[level]
    question_type = random.choice(_QUESTION_TYPES)

    if last_correct is True:
        depth_hint = "직전 문제를 맞혔습니다. 같은 영역에서 더 심화된 내용을 출제하세요."
    elif last_correct is False:
        depth_hint = "직전 문제를 틀렸습니다. 같은 영역의 다른 개념을 출제하세요."
    else:
        depth_hint = "첫 문제입니다. 기초적인 개념부터 시작하세요."

    dedup = ""
    if used_questions:
        prev_str = "\n".join(f"- {q}" for q in used_questions[:20])
        dedup = f"\n아래 문제들과 동일하거나 유사한 내용 출제 금지:\n{prev_str}\n"

    return (
        f"측정 영역: [{target_area}]\n"
        f"난이도: {level}/5 ({label})\n"
        f"문제 유형: {question_type}\n"
        f"심화 지침: {depth_hint}\n"
        f"{dedup}"
        f"JSON의 area 필드는 반드시 '{target_area}'로 설정하세요."
    )


def _parse_gemini_response(raw_text: str) -> dict:
    text = raw_text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if match:
        text = match.group(1).strip()
    return json.loads(text)


def _adjust_difficulty(current: float, is_correct: bool) -> float:
    if is_correct:
        return min(5.0, round(current + 0.5, 2))
    return max(1.0, round(current - 0.4, 2))


def _calculate_area_stats(session_id: str, settings) -> dict:
    """5개 영역별 정답률 계산 (0~5 점수)."""
    with connect_postgres(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT area, is_correct
                FROM quiz_questions
                WHERE session_id = %s
                  AND question_type = 'multiple_choice'
                  AND is_correct IS NOT NULL
                """,
                (session_id,),
            )
            rows = cur.fetchall()

    counts = {area: {"correct": 0, "total": 0} for area in AREAS}
    for row in rows:
        area = row["area"] if row["area"] in counts else "기본개념"
        counts[area]["total"] += 1
        if row["is_correct"]:
            counts[area]["correct"] += 1

    return {
        area: {
            "score": round((c["correct"] / c["total"]) * 5, 1) if c["total"] > 0 else None,
            "correct": c["correct"],
            "total": c["total"],
        }
        for area, c in counts.items()
    }


def _compute_tendency(session_id: str, settings) -> dict:
    with connect_postgres(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT topic, user_answer
                FROM quiz_questions
                WHERE session_id = %s AND question_type = 'preference' AND user_answer IS NOT NULL
                """,
                (session_id,),
            )
            rows = cur.fetchall()

    scores: dict[str, int] = {}
    for row in rows:
        q_key = row["topic"]
        answer = row["user_answer"]
        for tendency, weight in _TENDENCY_WEIGHTS.get(q_key, {}).get(answer, {}).items():
            scores[tendency] = scores.get(tendency, 0) + weight

    best = max(scores, key=lambda k: scores[k]) if scores else "탐색형"
    name, description, news_hint = _TENDENCY_INFO.get(best, _TENDENCY_INFO["탐색형"])
    return {"tendency": name, "tendency_description": description, "news_hint": news_hint}


def _weakest_areas(area_stats: dict) -> list[str]:
    """점수 낮은 순으로 영역 반환 (심층 분석용)."""
    tested = [(a, v["score"]) for a, v in area_stats.items() if v["score"] is not None]
    untested = [a for a, v in area_stats.items() if v["score"] is None]
    tested.sort(key=lambda x: x[1])
    return untested + [a for a, _ in tested]


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
                    (id, user_id, current_difficulty, questions_asked, correct_count,
                     status, started_at, created_at)
                VALUES (%s, %s, 1.0, 0, 0, 'in_progress', %s, %s)
                RETURNING id, current_difficulty, questions_asked, correct_count, status
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
    }


def get_session(session_id: str) -> dict | None:
    settings = get_settings()
    with connect_postgres(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, current_difficulty, questions_asked, correct_count,
                       status, area_stats, analysis_depth
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
        "knowledge_questions": KNOWLEDGE_QUESTIONS,
        "area_stats": row["area_stats"] or {},
        "analysis_depth": row["analysis_depth"] or "basic",
    }


def generate_next_question(session_id: str) -> dict:
    settings = get_settings()
    with connect_postgres(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT current_difficulty, questions_asked, status, analysis_depth, area_stats
                FROM quiz_sessions WHERE id = %s
                """,
                (session_id,),
            )
            session = cur.fetchone()
            if session is None:
                raise ValueError("세션을 찾을 수 없습니다.")
            if session["status"] not in ("in_progress", "deep_analysis"):
                raise ValueError("이미 완료된 세션입니다.")

    question_number = session["questions_asked"] + 1
    is_deep = session["status"] == "deep_analysis"

    if not is_deep and question_number > TOTAL_QUESTIONS:
        raise ValueError("모든 문제를 이미 출제했습니다.")

    # 성향 문제 (Q8~Q10)
    if not is_deep and question_number > KNOWLEDGE_QUESTIONS:
        return _get_preference_question(session_id, question_number, settings)

    # 지식 문제 (기본 Q1~Q7 or 심층)
    if is_deep:
        area_stats = session["area_stats"] or {}
        parsed_stats = {
            a: {"score": v.get("score"), "correct": v.get("correct", 0), "total": v.get("total", 0)}
            for a, v in area_stats.items()
        } if area_stats else {a: {"score": None, "correct": 0, "total": 0} for a in AREAS}
        weak = _weakest_areas(parsed_stats)
        target_area = weak[question_number % len(weak)] if weak else AREAS[0]
    else:
        target_area = _AREA_CYCLE[(question_number - 1) % len(_AREA_CYCLE)]

    return _get_knowledge_question(
        session_id, question_number, session["current_difficulty"], target_area, settings
    )


def _get_knowledge_question(
    session_id: str, question_number: int, difficulty: float, target_area: str, settings
) -> dict:
    from app.services.gemini.client import gemini_generate_content
    from psycopg.types.json import Jsonb

    with connect_postgres(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT qq.question_text, qq.is_correct
                FROM quiz_questions qq
                JOIN quiz_sessions qs ON qs.id = qq.session_id
                WHERE qq.question_type = 'multiple_choice'
                  AND (
                    qq.session_id = %s
                    OR (qs.user_id = (SELECT user_id FROM quiz_sessions WHERE id = %s) AND qs.user_id IS NOT NULL)
                  )
                ORDER BY qq.created_at DESC
                LIMIT 40
            """, (session_id, session_id))
            rows = cur.fetchall()

    used_questions = [r["question_text"][:30] for r in rows if r["question_text"]]
    last_correct = rows[0]["is_correct"] if rows else None

    raw = gemini_generate_content(
        system_prompt=_KNOWLEDGE_SYSTEM_PROMPT,
        user_prompt=_build_knowledge_prompt(difficulty, target_area, used_questions, last_correct),
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

    choices, correct_answer = _shuffle_choices(choices, correct_answer)

    area = parsed.get("area", target_area).strip()
    if area not in AREAS:
        area = target_area
    topic = parsed.get("topic", "").strip()
    topic_stored = f"{area}|{topic}" if topic else area

    question_id = str(uuid4())
    now = datetime.now(timezone.utc)
    with connect_postgres(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO quiz_questions
                    (id, session_id, question_number, question_text, question_type,
                     choices, correct_answer, explanation, difficulty, topic, area, created_at)
                VALUES (%s, %s, %s, %s, 'multiple_choice', %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    question_id, session_id, question_number, parsed["question_text"],
                    Jsonb(choices), correct_answer, parsed.get("explanation", ""),
                    difficulty, topic_stored, area, now,
                ),
            )

    return {
        "question_id": question_id,
        "question_number": question_number,
        "question_type": "knowledge",
        "area": area,
        "question_text": parsed["question_text"],
        "choices": choices,
        "difficulty": difficulty,
    }


def _get_preference_question(session_id: str, question_number: int, settings) -> dict:
    from psycopg.types.json import Jsonb

    offset = question_number - KNOWLEDGE_QUESTIONS - 1
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
        "area": None,
        "question_text": pq["question_text"],
        "choices": pq["choices"],
        "difficulty": None,
    }


def submit_answer(session_id: str, question_id: str, answer: str) -> dict:
    settings = get_settings()

    with connect_postgres(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT correct_answer, explanation, is_correct, question_type, area FROM quiz_questions WHERE id = %s AND session_id = %s",
                (question_id, session_id),
            )
            question = cur.fetchone()
            if question is None:
                raise ValueError("문항을 찾을 수 없습니다.")
            if question["is_correct"] is not None:
                raise ValueError("이미 답변한 문항입니다.")

            is_preference = question["question_type"] == "preference"
            is_모름 = answer == "E" and not is_preference
            is_correct = False if is_preference or is_모름 else (answer == question["correct_answer"])

            if is_preference:
                cur.execute("UPDATE quiz_questions SET user_answer = %s WHERE id = %s", (answer, question_id))
            else:
                cur.execute("UPDATE quiz_questions SET user_answer = %s, is_correct = %s WHERE id = %s",
                            (answer, is_correct, question_id))

            cur.execute(
                "SELECT current_difficulty, questions_asked, correct_count, status, analysis_depth FROM quiz_sessions WHERE id = %s",
                (session_id,),
            )
            session = cur.fetchone()
            is_deep = session["status"] == "deep_analysis"
            new_questions_asked = session["questions_asked"] + 1

            if is_preference:
                new_difficulty = session["current_difficulty"]
                new_correct_count = session["correct_count"]
            else:
                new_difficulty = _adjust_difficulty(session["current_difficulty"], is_correct)
                new_correct_count = session["correct_count"] + (1 if is_correct else 0)

            # 완료 조건
            basic_done = not is_deep and new_questions_asked >= TOTAL_QUESTIONS
            deep_done = is_deep and new_questions_asked >= (TOTAL_QUESTIONS + DEEP_EXTRA_QUESTIONS)

            if basic_done or deep_done:
                area_stats = _calculate_area_stats(session_id, settings)
                tendency_info = _compute_tendency(session_id, settings)
                from psycopg.types.json import Jsonb

                new_status = "completed"
                now = datetime.now(timezone.utc)
                cur.execute(
                    """
                    UPDATE quiz_sessions
                    SET current_difficulty = %s, questions_asked = %s, correct_count = %s,
                        status = %s, area_stats = %s, completed_at = %s
                    WHERE id = %s
                    """,
                    (new_difficulty, new_questions_asked, new_correct_count,
                     new_status, Jsonb(area_stats), now, session_id),
                )
            else:
                area_stats = None
                tendency_info = None
                new_status = session["status"]
                cur.execute(
                    "UPDATE quiz_sessions SET current_difficulty = %s, questions_asked = %s, correct_count = %s WHERE id = %s",
                    (new_difficulty, new_questions_asked, new_correct_count, session_id),
                )

    result = {
        "is_correct": is_correct,
        "is_모름": is_모름,
        "is_preference": is_preference,
        "correct_answer": question["correct_answer"] if not is_preference else None,
        "explanation": question["explanation"] if not is_preference else None,
        "session_status": new_status,
        "questions_asked": new_questions_asked,
        "correct_count": new_correct_count,
        "total_questions": TOTAL_QUESTIONS if not is_deep else TOTAL_QUESTIONS + DEEP_EXTRA_QUESTIONS,
        "knowledge_questions": KNOWLEDGE_QUESTIONS,
        "area_stats": area_stats,
        "tendency": tendency_info["tendency"] if tendency_info else None,
        "tendency_description": tendency_info["tendency_description"] if tendency_info else None,
        "news_hint": tendency_info["news_hint"] if tendency_info else None,
    }
    return result


def start_deep_analysis(session_id: str) -> dict:
    """기본 퀴즈 완료 후 심층 분석 시작."""
    settings = get_settings()
    with connect_postgres(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status, questions_asked FROM quiz_sessions WHERE id = %s",
                (session_id,),
            )
            session = cur.fetchone()
            if session is None:
                raise ValueError("세션을 찾을 수 없습니다.")
            if session["status"] != "completed":
                raise ValueError("기본 퀴즈를 먼저 완료해야 합니다.")

            cur.execute(
                """
                UPDATE quiz_sessions
                SET status = 'deep_analysis', analysis_depth = 'deep',
                    completed_at = NULL
                WHERE id = %s
                """,
                (session_id,),
            )

    return {
        "session_id": session_id,
        "status": "deep_analysis",
        "deep_questions_remaining": DEEP_EXTRA_QUESTIONS,
        "message": f"심층 분석을 시작합니다. {DEEP_EXTRA_QUESTIONS}개 문제를 추가로 풀어주세요.",
    }
