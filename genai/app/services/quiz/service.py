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

_SYSTEM_PROMPT = """당신은 금융 투자 교육 전문가입니다. 주어진 난이도에 맞는 금융 지식 퀴즈 문제를 생성합니다.

문제 유형: 객관식 4지선다 (A, B, C, D)
언어: 한국어
분야: 주식, 채권, ETF, 펀드, 경제 지표, 기업 재무, 투자 전략, 파생상품 등 금융 전반

난이도 기준:
- 1 (입문): 주식이란 무엇인가, 분산투자의 개념, 기본 금융 용어
- 2 (기초): PER, PBR, 배당수익률, 시가총액, 코스피/코스닥 개념
- 3 (중급): EBITDA, 베타계수, 듀레이션, 공매도, 리밸런싱
- 4 (고급): 옵션 전략, DCF 모델, 부채비율 분석, 금리와 채권 관계
- 5 (전문가): 블랙숄즈 모델, 포트폴리오 최적화, 차익거래, 파생상품 헤징

반드시 다음 JSON 형식으로만 응답하세요. JSON 외의 텍스트는 절대 포함하지 마세요:
{
  "question_text": "문제 내용 (구체적이고 명확하게)",
  "choices": {
    "A": "선택지 A 내용",
    "B": "선택지 B 내용",
    "C": "선택지 C 내용",
    "D": "선택지 D 내용"
  },
  "correct_answer": "A",
  "explanation": "정답 설명 (2~3문장, 핵심 개념 포함)",
  "topic": "주제 키워드 (예: PER, 채권, 옵션)"
}"""


def _build_user_prompt(difficulty: float, used_topics: list[str]) -> str:
    level = max(1, min(5, round(difficulty)))
    label = _DIFFICULTY_LABELS[level]
    topics_str = ", ".join(used_topics[-5:]) if used_topics else "없음"
    return (
        f"난이도 {level}/5 ({label}) 수준의 금융 퀴즈 문제 1개를 생성해주세요.\n"
        f"이미 출제된 주제 (중복 금지): {topics_str}"
    )


def _parse_gemini_response(raw_text: str) -> dict:
    text = raw_text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if match:
        text = match.group(1).strip()
    return json.loads(text)


def _adjust_difficulty(current: float, is_correct: bool) -> float:
    if is_correct:
        return min(5.0, round(current + 0.4, 2))
    return max(1.0, round(current - 0.3, 2))


def _compute_final_level(difficulty: float) -> int:
    return max(1, min(5, round(difficulty)))


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
                FROM quiz_sessions
                WHERE id = %s
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
        temperature=0.7,
        request_label="quiz_question",
    )
    parsed = _parse_gemini_response(raw)

    choices = parsed["choices"]
    if not isinstance(choices, dict) or set(choices.keys()) != {"A", "B", "C", "D"}:
        raise RuntimeError("Gemini가 올바른 선택지 형식을 반환하지 않았습니다.")
    correct_answer = parsed["correct_answer"].strip().upper()
    if correct_answer not in {"A", "B", "C", "D"}:
        raise RuntimeError("Gemini가 올바른 정답 형식을 반환하지 않았습니다.")

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
                    question_id,
                    session_id,
                    question_number,
                    parsed["question_text"],
                    Jsonb(choices),
                    correct_answer,
                    parsed.get("explanation", ""),
                    difficulty,
                    parsed.get("topic", ""),
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

    with connect_postgres(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT correct_answer, explanation, is_correct
                FROM quiz_questions
                WHERE id = %s AND session_id = %s
                """,
                (question_id, session_id),
            )
            question = cur.fetchone()
            if question is None:
                raise ValueError("문항을 찾을 수 없습니다.")
            if question["is_correct"] is not None:
                raise ValueError("이미 답변한 문항입니다.")

            is_correct = answer == question["correct_answer"]
            cur.execute(
                "UPDATE quiz_questions SET user_answer = %s, is_correct = %s WHERE id = %s",
                (answer, is_correct, question_id),
            )

            cur.execute(
                "SELECT current_difficulty, questions_asked, correct_count FROM quiz_sessions WHERE id = %s",
                (session_id,),
            )
            session = cur.fetchone()
            new_difficulty = _adjust_difficulty(session["current_difficulty"], is_correct)
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

    return {
        "is_correct": is_correct,
        "correct_answer": question["correct_answer"],
        "explanation": question["explanation"] or "",
        "session_status": session_status,
        "questions_asked": new_questions_asked,
        "correct_count": new_correct_count,
        "total_questions": TOTAL_QUESTIONS,
        "final_level": final_level,
    }
