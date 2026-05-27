from pydantic import BaseModel, Field
from typing import Any


# ── 요청 ───────────────────────────────────────────────────────────────────────

class QuizStartRequest(BaseModel):
    user_id: str | None = None  # 비로그인도 허용


class QuizAnswerRequest(BaseModel):
    session_id: str
    question_id: str
    answer: str = Field(..., description="선택한 보기 키 (A/B/C/D 또는 O/X)")


# ── 응답 ───────────────────────────────────────────────────────────────────────

class QuizStartResponse(BaseModel):
    session_id: str
    min_questions: int
    max_questions: int
    initial_difficulty: float


class QuizQuestionResponse(BaseModel):
    question_id: str
    question_number: int
    total_questions_range: str
    question: str
    type: str  # "multiple_choice" | "ox"
    choices: dict[str, str]
    difficulty: float


class QuizAnswerResponse(BaseModel):
    is_correct: bool
    correct_answer: str
    explanation: str | None = None
    new_difficulty: float
    questions_answered: int
    correct_count: int
    is_finished: bool
    final_level: int | None = None


class QuizQuestionResult(BaseModel):
    number: int
    question: str
    type: str
    choices: dict[str, str]
    correct_answer: str
    user_answer: str | None = None
    is_correct: bool | None = None
    explanation: str | None = None
    difficulty: float | None = None


class QuizResultResponse(BaseModel):
    session_id: str
    status: str
    final_level: int
    level_description: str
    questions_answered: int
    correct_count: int
    accuracy_percent: float
    questions: list[QuizQuestionResult]
    started_at: str | None = None
    completed_at: str | None = None
