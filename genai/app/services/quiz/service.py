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

TOTAL_QUESTIONS: int = 10           # 5영역 × 2문제
KNOWLEDGE_QUESTIONS: int = 10
DEEP_EXTRA_QUESTIONS: int = 5       # 심층 분석 추가 문제 수

# 5개 측정 영역 (오각형 스탯)
AREAS = ["기본개념", "마켓수급", "매크로", "펀더멘털", "리스크관리"]

# 각 영역 2번씩 순환 (1라운드 → 2라운드 난이도 상승)
_AREA_CYCLE = ["기본개념", "마켓수급", "매크로", "펀더멘털", "리스크관리",
               "기본개념", "마켓수급", "매크로", "펀더멘털", "리스크관리"]

_DIFFICULTY_LABELS = {1: "입문", 2: "기초", 3: "중급", 4: "고급", 5: "전문가"}

# 영역 → 대표 성향 매핑 (emoji, 타입명, 설명, 뉴스 분석 안내)
_AREA_TENDENCY = {
    "기본개념": (
        "🌱", "탐색형 투자자",
        "투자의 기초를 탄탄히 쌓아가는 단계입니다. 다양한 개념을 골고루 접하며 나만의 스타일을 찾아가고 있어요.",
        ["기초 용어 설명이 포함된 쉬운 해설", "다양한 섹터의 입문 뉴스", "개념 풀이 위주의 감성 분석"],
    ),
    "마켓수급": (
        "📈", "모멘텀형 투자자",
        "시장의 흐름과 수급을 빠르게 읽는 능력이 있습니다. 단기 모멘텀과 기술적 신호에 민감하게 반응하는 스타일이에요.",
        ["시장 수급·거래량 변화 분석", "기술적 신호(RSI·MACD) 해설", "핫 섹터·테마주 동향"],
    ),
    "매크로": (
        "🌍", "거시경제형 투자자",
        "금리·환율·경기 사이클 등 큰 그림에서 투자 방향을 잡는 능력이 뛰어납니다. 시장 전체의 방향을 읽는 눈이 있어요.",
        ["금리·환율·GDP 변동이 주가에 미치는 영향 분석", "연준·한국은행 통화정책 해설", "거시경제 관점의 섹터 분석"],
    ),
    "펀더멘털": (
        "🔍", "가치투자형 투자자",
        "재무제표와 밸류에이션 지표를 통해 기업의 내재가치를 꼼꼼히 분석하는 스타일입니다. 저평가 종목 발굴에 강점이 있어요.",
        ["기업 실적·EPS·PER 중심의 재무 분석", "저평가 종목 발굴 시그널", "분기 실적 발표 해설"],
    ),
    "리스크관리": (
        "🛡️", "안정추구형 투자자",
        "손실 방어와 포트폴리오 안정성을 최우선으로 생각합니다. 리스크 대비 수익을 철저히 따지는 신중한 스타일이에요.",
        ["변동성·베타계수 리스크 지표 해설", "배당주·채권 안정 자산 분석", "포트폴리오 분산 관점의 뉴스"],
    ),
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
    area_score: float | None = None,
) -> str:
    import random
    level = max(1, min(5, round(difficulty)))
    label = _DIFFICULTY_LABELS[level]
    question_type = random.choice(_QUESTION_TYPES)

    if area_score is not None and area_score >= 4.0:
        depth_hint = f"[심층 확인] 이 영역 점수가 {area_score}/5으로 높습니다. 일반적으로 알려지지 않은 심화 개념이나 응용 계산 문제로 실제 이해 깊이를 확인하세요."
    elif area_score is not None and area_score < 2.0:
        depth_hint = f"[기초 확인] 이 영역 점수가 {area_score}/5으로 낮습니다. 아주 기초적인 개념 문제부터 다시 시작해 어느 수준까지 아는지 파악하세요."
    elif last_correct is True:
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


def _compute_tendency(area_stats: dict) -> dict:
    """오각형 스탯에서 대표 성향 자동 도출 — 가장 강한 영역 기준."""
    tested = {a: v["score"] for a, v in area_stats.items() if v.get("score") is not None}
    strongest = max(tested, key=lambda k: tested[k]) if tested else "기본개념"
    emoji, label, description, analysis_hints = _AREA_TENDENCY[strongest]
    return {
        "tendency": label,
        "tendency_emoji": emoji,
        "tendency_description": description,
        "analysis_hints": analysis_hints,
        "strongest_area": strongest,
    }


def _deep_analysis_order(area_stats: dict) -> list[str]:
    """심층 분석 순서: 만점/고득점 영역(심화 확인) → 저득점 영역(기초 확인) 순."""
    high = [(a, v["score"]) for a, v in area_stats.items() if v["score"] is not None and v["score"] >= 4.0]
    low  = [(a, v["score"]) for a, v in area_stats.items() if v["score"] is not None and v["score"] < 2.5]
    mid  = [(a, v["score"]) for a, v in area_stats.items() if v["score"] is not None and 2.5 <= v["score"] < 4.0]
    none = [a for a, v in area_stats.items() if v["score"] is None]
    high.sort(key=lambda x: -x[1])
    low.sort(key=lambda x: x[1])
    ordered = [a for a, _ in high] + none + [a for a, _ in low] + [a for a, _ in mid]
    return ordered if ordered else AREAS


def _deep_difficulty(base: float, area_score: float | None) -> float:
    """영역 점수에 따라 심층 문제 난이도 결정."""
    if area_score is None:
        return max(1.0, base)
    if area_score >= 4.0:
        return min(5.0, round(area_score + 0.5, 1))  # 고득점 → 더 어려운 문제
    if area_score < 2.0:
        return max(1.0, round(area_score, 1))          # 저득점 → 쉬운 문제로 바닥 확인
    return round(area_score, 1)                         # 중간 → 해당 점수 수준


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

    # 지식 문제 (기본 Q1~Q10 or 심층)
    if is_deep:
        area_stats = session["area_stats"] or {}
        parsed_stats = {
            a: {"score": v.get("score"), "correct": v.get("correct", 0), "total": v.get("total", 0)}
            for a, v in area_stats.items()
        } if area_stats else {a: {"score": None, "correct": 0, "total": 0} for a in AREAS}

        # 심층 문제 인덱스 (0~4): 강한→심화, 약한→기초 확인 순서
        deep_idx = question_number - TOTAL_QUESTIONS - 1
        ordered = _deep_analysis_order(parsed_stats)
        target_area = ordered[deep_idx % len(ordered)]
        area_score = parsed_stats.get(target_area, {}).get("score")
        deep_difficulty = _deep_difficulty(session["current_difficulty"], area_score)
    else:
        target_area = _AREA_CYCLE[(question_number - 1) % len(_AREA_CYCLE)]
        deep_difficulty = None
        area_score = None

    return _get_knowledge_question(
        session_id, question_number,
        deep_difficulty if deep_difficulty is not None else session["current_difficulty"],
        target_area, settings,
        area_score=area_score,
    )


def _get_knowledge_question(
    session_id: str, question_number: int, difficulty: float, target_area: str, settings,
    area_score: float | None = None,
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
        user_prompt=_build_knowledge_prompt(difficulty, target_area, used_questions, last_correct, area_score=area_score),
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

            is_모름 = answer == "E"
            is_correct = False if is_모름 else (answer == question["correct_answer"])
            cur.execute("UPDATE quiz_questions SET user_answer = %s, is_correct = %s WHERE id = %s",
                        (answer, is_correct, question_id))

            cur.execute(
                "SELECT current_difficulty, questions_asked, correct_count, status FROM quiz_sessions WHERE id = %s",
                (session_id,),
            )
            session = cur.fetchone()
            is_deep = session["status"] == "deep_analysis"
            new_questions_asked = session["questions_asked"] + 1
            new_difficulty = _adjust_difficulty(session["current_difficulty"], is_correct)
            new_correct_count = session["correct_count"] + (1 if is_correct else 0)

            basic_done = not is_deep and new_questions_asked >= TOTAL_QUESTIONS
            deep_done = is_deep and new_questions_asked >= (TOTAL_QUESTIONS + DEEP_EXTRA_QUESTIONS)

            if basic_done or deep_done:
                area_stats = _calculate_area_stats(session_id, settings)
                tendency_info = _compute_tendency(area_stats)
                from psycopg.types.json import Jsonb
                cur.execute(
                    """
                    UPDATE quiz_sessions
                    SET current_difficulty = %s, questions_asked = %s, correct_count = %s,
                        status = 'completed', area_stats = %s, completed_at = %s
                    WHERE id = %s
                    """,
                    (new_difficulty, new_questions_asked, new_correct_count,
                     Jsonb(area_stats), datetime.now(timezone.utc), session_id),
                )
                new_status = "completed"
            else:
                area_stats = None
                tendency_info = None
                new_status = session["status"]
                cur.execute(
                    "UPDATE quiz_sessions SET current_difficulty = %s, questions_asked = %s, correct_count = %s WHERE id = %s",
                    (new_difficulty, new_questions_asked, new_correct_count, session_id),
                )

    return {
        "is_correct": is_correct,
        "is_모름": is_모름,
        "is_preference": False,
        "correct_answer": question["correct_answer"],
        "explanation": question["explanation"],
        "session_status": new_status,
        "questions_asked": new_questions_asked,
        "correct_count": new_correct_count,
        "total_questions": TOTAL_QUESTIONS if not is_deep else TOTAL_QUESTIONS + DEEP_EXTRA_QUESTIONS,
        "knowledge_questions": KNOWLEDGE_QUESTIONS,
        "area_stats": area_stats,
        "tendency": tendency_info["tendency"] if tendency_info else None,
        "tendency_emoji": tendency_info.get("tendency_emoji") if tendency_info else None,
        "tendency_description": tendency_info["tendency_description"] if tendency_info else None,
        "analysis_hints": tendency_info.get("analysis_hints") if tendency_info else None,
        "strongest_area": tendency_info.get("strongest_area") if tendency_info else None,
    }


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
