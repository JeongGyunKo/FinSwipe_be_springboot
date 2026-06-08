from __future__ import annotations

import uuid as _uuid_module
from typing import Optional, Any

from pydantic import BaseModel, Field, field_validator


def _validate_uuid_or_none(v: Optional[str]) -> Optional[str]:
    if v is None:
        return v
    try:
        _uuid_module.UUID(v)
    except ValueError:
        raise ValueError("UUID 형식이어야 합니다")
    return v


class CreateSessionRequest(BaseModel):
    user_id: Optional[str] = Field(default=None, max_length=36)

    @field_validator("user_id")
    @classmethod
    def user_id_must_be_uuid(cls, v: Optional[str]) -> Optional[str]:
        return _validate_uuid_or_none(v)


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
    question_type: str
    area: Optional[str] = None
    question_text: str
    choices: dict[str, str]
    difficulty: Optional[float] = None


class SubmitAnswerRequest(BaseModel):
    question_id: Optional[str] = Field(default=None, max_length=36)
    answer: str = Field(..., max_length=1)

    @field_validator("question_id")
    @classmethod
    def question_id_must_be_uuid(cls, v: Optional[str]) -> Optional[str]:
        return _validate_uuid_or_none(v)

    @field_validator("answer")
    @classmethod
    def answer_must_be_valid(cls, v: str) -> str:
        normalized = v.strip().upper()
        if normalized not in {"A", "B", "C", "D", "E"}:
            raise ValueError("답은 A~E 중 하나여야 합니다.")
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
    area_stats: Optional[dict[str, Any]] = None
    tendency: Optional[str] = None
    tendency_emoji: Optional[str] = None
    tendency_description: Optional[str] = None
    analysis_hints: Optional[list[str]] = None
    strongest_area: Optional[str] = None


class DeepAnalysisResponse(BaseModel):
    session_id: str
    status: str
    deep_questions_remaining: int
    message: str
