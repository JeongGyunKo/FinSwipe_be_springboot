"""퀴즈 서비스 — 적응형 난이도 레벨 테스트"""
import json
import logging
import uuid
from datetime import datetime, timezone

from app.database import get_pool
from app.prompts.quiz_prompts import QUIZ_SYSTEM, build_quiz_messages
from app.services.gemini_client import call_gemini, extract_json

logger = logging.getLogger(__name__)

# 퀴즈 설정
MIN_QUESTIONS = 10
MAX_QUESTIONS = 15
INITIAL_DIFFICULTY = 2.0
DIFFICULTY_STEP_CORRECT = 0.5
DIFFICULTY_STEP_WRONG = 0.5
DIFFICULTY_MIN = 1.0
DIFFICULTY_MAX = 5.0


async def start_quiz(user_id: str | None = None) -> dict:
    """퀴즈 세션 시작"""
    pool = get_pool()
    session_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    await pool.execute(
        """
        INSERT INTO quiz_sessions
            (id, user_id, current_difficulty, questions_asked,
             correct_count, status, started_at, created_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $7)
        """,
        session_id, user_id, INITIAL_DIFFICULTY,
        0, 0, "in_progress", now,
    )

    return {
        "session_id": session_id,
        "min_questions": MIN_QUESTIONS,
        "max_questions": MAX_QUESTIONS,
        "initial_difficulty": INITIAL_DIFFICULTY,
    }


async def get_next_question(session_id: str) -> dict:
    """다음 문제 생성 (적응형 난이도)"""
    pool = get_pool()

    session = await pool.fetchrow(
        "SELECT * FROM quiz_sessions WHERE id = $1", session_id
    )
    if not session:
        raise ValueError(f"세션을 찾을 수 없습니다: {session_id}")
    if session["status"] != "in_progress":
        raise ValueError("이미 완료된 세션입니다.")

    q_count = session["questions_asked"]
    if q_count >= MAX_QUESTIONS:
        raise ValueError("최대 문제 수에 도달했습니다. 결과를 확인하세요.")

    # 이미 출제된 주제 목록 조회
    asked_rows = await pool.fetch(
        "SELECT topic FROM quiz_questions WHERE session_id = $1 ORDER BY question_number",
        session_id,
    )
    asked_topics = [r["topic"] for r in asked_rows if r["topic"]]

    difficulty = float(session["current_difficulty"])
    messages = build_quiz_messages(difficulty, asked_topics)

    try:
        raw = await call_gemini(
            system=QUIZ_SYSTEM,
            messages=messages,
            use_thinking=True,  # thinking 모드로 정교한 문제 생성
            max_tokens=2048,
        )
        data = extract_json(raw)
    except Exception as e:
        logger.error("[퀴즈] 문제 생성 실패: %s | %s", session_id, e)
        raise RuntimeError("문제 생성에 실패했습니다. 잠시 후 다시 시도하세요.")

    question_id = str(uuid.uuid4())
    question_number = q_count + 1
    now = datetime.now(timezone.utc)

    # 주제 추출 (문제 텍스트의 첫 10자 사용)
    topic = data.get("question", "")[:30]

    await pool.execute(
        """
        INSERT INTO quiz_questions
            (id, session_id, question_number, question_text, question_type,
             choices, correct_answer, explanation, difficulty, topic, created_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        """,
        question_id,
        session_id,
        question_number,
        data.get("question"),
        data.get("type", "multiple_choice"),
        json.dumps(data.get("choices", {}), ensure_ascii=False),
        data.get("answer"),
        data.get("explanation"),
        float(data.get("difficulty", difficulty)),
        topic,
        now,
    )

    return {
        "question_id": question_id,
        "question_number": question_number,
        "total_questions_range": f"{MIN_QUESTIONS}~{MAX_QUESTIONS}",
        "question": data.get("question"),
        "type": data.get("type", "multiple_choice"),
        "choices": data.get("choices", {}),
        "difficulty": float(data.get("difficulty", difficulty)),
    }


async def submit_answer(session_id: str, question_id: str, answer: str) -> dict:
    """답변 제출 및 난이도 조정"""
    pool = get_pool()

    session = await pool.fetchrow(
        "SELECT * FROM quiz_sessions WHERE id = $1", session_id
    )
    if not session:
        raise ValueError(f"세션을 찾을 수 없습니다: {session_id}")
    if session["status"] != "in_progress":
        raise ValueError("이미 완료된 세션입니다.")

    question = await pool.fetchrow(
        "SELECT * FROM quiz_questions WHERE id = $1 AND session_id = $2",
        question_id, session_id,
    )
    if not question:
        raise ValueError("문제를 찾을 수 없습니다.")
    if question["user_answer"] is not None:
        raise ValueError("이미 답변한 문제입니다.")

    # 정답 확인
    correct_answer = question["correct_answer"]
    is_correct = answer.strip().upper() == correct_answer.strip().upper()

    # 난이도 조정
    current_difficulty = float(session["current_difficulty"])
    if is_correct:
        new_difficulty = min(DIFFICULTY_MAX, current_difficulty + DIFFICULTY_STEP_CORRECT)
    else:
        new_difficulty = max(DIFFICULTY_MIN, current_difficulty - DIFFICULTY_STEP_WRONG)

    questions_asked = session["questions_asked"] + 1
    correct_count = session["correct_count"] + (1 if is_correct else 0)
    now = datetime.now(timezone.utc)

    # 문제 답변 기록
    await pool.execute(
        "UPDATE quiz_questions SET user_answer = $1, is_correct = $2 WHERE id = $3",
        answer, is_correct, question_id,
    )

    # 세션 업데이트
    # 종료 조건: MAX 문제 도달 OR (MIN 문제 이상 AND 난이도가 극단값)
    should_finish = (
        questions_asked >= MAX_QUESTIONS
        or (questions_asked >= MIN_QUESTIONS and (
            new_difficulty >= DIFFICULTY_MAX
            or new_difficulty <= DIFFICULTY_MIN
        ))
    )

    if should_finish:
        final_level_val = _calc_level_from_difficulty(new_difficulty, correct_count, questions_asked)
        await pool.execute(
            """
            UPDATE quiz_sessions
            SET current_difficulty = $1, questions_asked = $2, correct_count = $3,
                status = 'completed', final_level = $4, completed_at = $5
            WHERE id = $6
            """,
            new_difficulty, questions_asked, correct_count,
            final_level_val, now, session_id,
        )
    else:
        await pool.execute(
            """
            UPDATE quiz_sessions
            SET current_difficulty = $1, questions_asked = $2, correct_count = $3
            WHERE id = $4
            """,
            new_difficulty, questions_asked, correct_count, session_id,
        )
        final_level_val = None

    return {
        "is_correct": is_correct,
        "correct_answer": correct_answer,
        "explanation": question["explanation"],
        "new_difficulty": new_difficulty,
        "questions_answered": questions_asked,
        "correct_count": correct_count,
        "is_finished": should_finish,
        "final_level": final_level_val if should_finish else None,
    }


async def get_quiz_result(session_id: str) -> dict:
    """최종 레벨 결과 조회"""
    pool = get_pool()

    session = await pool.fetchrow(
        "SELECT * FROM quiz_sessions WHERE id = $1", session_id
    )
    if not session:
        raise ValueError(f"세션을 찾을 수 없습니다: {session_id}")

    questions = await pool.fetch(
        """
        SELECT question_number, question_text, question_type, choices,
               correct_answer, user_answer, is_correct, explanation, difficulty
        FROM quiz_questions
        WHERE session_id = $1
        ORDER BY question_number
        """,
        session_id,
    )

    q_count = session["questions_asked"]
    correct = session["correct_count"]
    accuracy = round(correct / q_count * 100, 1) if q_count > 0 else 0.0

    final_level = session["final_level"]
    if final_level is None:
        # 세션이 아직 진행 중이거나 final_level이 미설정
        final_level = _calc_level_from_difficulty(
            float(session["current_difficulty"]), correct, q_count
        )

    level_descriptions = {
        1: "입문자 — 주식 기초 개념을 배우는 단계",
        2: "초보자 — 기본 주식 용어를 이해하는 단계",
        3: "중급자 — PER/PBR 등 주요 지표를 이해하는 단계",
        4: "고급자 — 재무제표 분석이 가능한 단계",
        5: "전문가 — 매크로경제와 고급 전략을 이해하는 단계",
    }

    return {
        "session_id": session_id,
        "status": session["status"],
        "final_level": final_level,
        "level_description": level_descriptions.get(final_level, ""),
        "questions_answered": q_count,
        "correct_count": correct,
        "accuracy_percent": accuracy,
        "questions": [
            {
                "number": q["question_number"],
                "question": q["question_text"],
                "type": q["question_type"],
                "choices": json.loads(q["choices"]) if q["choices"] else {},
                "correct_answer": q["correct_answer"],
                "user_answer": q["user_answer"],
                "is_correct": q["is_correct"],
                "explanation": q["explanation"],
                "difficulty": float(q["difficulty"]) if q["difficulty"] else None,
            }
            for q in questions
        ],
        "started_at": session["started_at"].isoformat() if session["started_at"] else None,
        "completed_at": session["completed_at"].isoformat() if session["completed_at"] else None,
    }


def _calc_level_from_difficulty(difficulty: float, correct: int, total: int) -> int:
    """난이도와 정답률 기반 최종 레벨 계산"""
    # 기본: 최종 난이도를 반올림
    base_level = round(difficulty)
    # 정답률 보정: 80% 이상이면 +0 (유지), 40% 미만이면 -1 하향
    if total > 0:
        accuracy = correct / total
        if accuracy < 0.4 and base_level > 1:
            base_level -= 1
    return max(1, min(5, base_level))
