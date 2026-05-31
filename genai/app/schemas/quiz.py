from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, field_validator


class CreateSessionRequest(BaseModel):
    user_id: Optional[str] = None


class SessionResponse(BaseModel):
    session_id: str
    status: str
    current_difficulty: float
    questions_asked: int
    correct_count: int
    total_questions: int
    final_level: Optional[int] = None


class QuestionResponse(BaseModel):
    question_id: str
    question_number: int
    question_text: str
    choices: dict[str, str]
    difficulty: float


class SubmitAnswerRequest(BaseModel):
    question_id: str
    answer: str

    @field_validator("answer")
    @classmethod
    def answer_must_be_valid(cls, v: str) -> str:
        normalized = v.strip().upper()
        if normalized not in {"A", "B", "C", "D"}:
            raise ValueError("답은 A, B, C, D 중 하나여야 합니다.")
        return normalized


class AnswerResultResponse(BaseModel):
    is_correct: bool
    correct_answer: str
    explanation: str
    session_status: str
    questions_asked: int
    correct_count: int
    total_questions: int
    final_level: Optional[int] = None
