from __future__ import annotations

import asyncio
import uuid as _uuid_module

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.schemas.quiz import (
    AnswerResultResponse,
    CreateSessionRequest,
    DeepAnalysisResponse,
    QuestionResponse,
    SessionResponse,
    SubmitAnswerRequest,
)
from app.services.quiz import service as quiz_service

router = APIRouter(prefix="/quiz", tags=["quiz"])


def _require_uuid(session_id: str) -> str:
    try:
        _uuid_module.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="유효하지 않은 session_id")
    return session_id


@router.post("/sessions", response_model=SessionResponse, status_code=201)
async def create_quiz_session(body: CreateSessionRequest, background_tasks: BackgroundTasks) -> SessionResponse:
    try:
        result = await asyncio.to_thread(quiz_service.create_session, body.user_id)
        # Q1을 세션 생성 직후부터 미리 생성 — next-question 호출 시 대기 시간 단축
        background_tasks.add_task(
            asyncio.to_thread, quiz_service.prefetch_next_question_content, result["session_id"]
        )
        return SessionResponse(**result)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_quiz_session(session_id: str) -> SessionResponse:
    _require_uuid(session_id)
    result = await asyncio.to_thread(quiz_service.get_session, session_id)
    if result is None:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")
    return SessionResponse(**result)


@router.post("/sessions/{session_id}/next-question", response_model=QuestionResponse)
async def next_question(session_id: str) -> QuestionResponse:
    _require_uuid(session_id)
    try:
        result = await asyncio.to_thread(quiz_service.generate_next_question, session_id)
        return QuestionResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail="문제 생성 중 오류가 발생했습니다.") from exc


@router.post("/sessions/{session_id}/answers", response_model=AnswerResultResponse)
async def submit_answer(session_id: str, body: SubmitAnswerRequest, background_tasks: BackgroundTasks) -> AnswerResultResponse:
    _require_uuid(session_id)
    try:
        result = await asyncio.to_thread(
            quiz_service.submit_answer, session_id, body.question_id, body.answer,
        )
        # 세션이 완료되지 않은 경우, 다음 문제를 백그라운드에서 미리 생성
        if result["session_status"] != "completed":
            background_tasks.add_task(
                asyncio.to_thread, quiz_service.prefetch_next_question_content, session_id
            )
        return AnswerResultResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/sessions/{session_id}/deep", response_model=DeepAnalysisResponse)
async def start_deep_analysis(session_id: str) -> DeepAnalysisResponse:
    """기본 퀴즈 완료 후 심층 분석 시작."""
    _require_uuid(session_id)
    try:
        result = await asyncio.to_thread(quiz_service.start_deep_analysis, session_id)
        return DeepAnalysisResponse(**result)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
