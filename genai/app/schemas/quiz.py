from __future__ import annotations

from typing import Optional, Any

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
    knowledge_questions: int
    area_stats: Optional[dict[str, Any]] = None
    analysis_depth: Optional[str] = "basic"


class QuestionResponse(BaseModel):
    question_id: str
    question_number: int
    question_type: str          # "knowledge" | "preference"
    area: Optional[str] = None
    question_text: str
    choices: dict[str, str]
    difficulty: Optional[float] = None


class SubmitAnswerRequest(BaseModel):
    question_id: str
    answer: str

    @field_validator("answer")
    @classmethod
    def answer_must_be_valid(cls, v: str) -> str:
        normalized = v.strip().upper()
        if normalized not in {"A", "B", "C", "D", "E"}:
            raise ValueError("답은 A, B, C, D, E 중 하나여야 합니다.")
        return normalized


class AnswerResultResponse(BaseModel):
    is_correct: bool
    is_모름: bool
    is_preference: bool
    correct_answer: Optional[str] = None
    explanation: Optional[str] = None
    session_status: str
    questions_asked: int
    correct_count: int
    total_questions: int
    knowledge_questions: int
    # 완료 시
    area_stats: Optional[dict[str, Any]] = None
    tendency: Optional[str] = None
    tendency_description: Optional[str] = None
    news_hint: Optional[str] = None


class DeepAnalysisResponse(BaseModel):
    session_id: str
    status: str
    deep_questions_remaining: int
    message: str
