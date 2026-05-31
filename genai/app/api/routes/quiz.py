from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException

from app.schemas.quiz import (
    AnswerResultResponse,
    CreateSessionRequest,
    QuestionResponse,
    SessionResponse,
    SubmitAnswerRequest,
)
from app.services.quiz import service as quiz_service

router = APIRouter(prefix="/quiz", tags=["quiz"])


@router.post("/sessions", response_model=SessionResponse, status_code=201)
async def create_quiz_session(body: CreateSessionRequest) -> SessionResponse:
    try:
        result = await asyncio.to_thread(quiz_service.create_session, body.user_id)
        return SessionResponse(**result)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_quiz_session(session_id: str) -> SessionResponse:
    result = await asyncio.to_thread(quiz_service.get_session, session_id)
    if result is None:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")
    return SessionResponse(**result)


@router.post("/sessions/{session_id}/next-question", response_model=QuestionResponse)
async def next_question(session_id: str) -> QuestionResponse:
    try:
        result = await asyncio.to_thread(quiz_service.generate_next_question, session_id)
        return QuestionResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=f"문제 생성 실패: {exc}") from exc


@router.post("/sessions/{session_id}/answers", response_model=AnswerResultResponse)
async def submit_answer(session_id: str, body: SubmitAnswerRequest) -> AnswerResultResponse:
    try:
        result = await asyncio.to_thread(
            quiz_service.submit_answer,
            session_id,
            body.question_id,
            body.answer,
        )
        return AnswerResultResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
