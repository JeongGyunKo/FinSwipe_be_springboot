"""퀴즈 API — 사용자 레벨 테스트"""
import logging

from fastapi import APIRouter, HTTPException, Path

from app.schemas.quiz import (
    QuizStartRequest,
    QuizStartResponse,
    QuizQuestionResponse,
    QuizAnswerRequest,
    QuizAnswerResponse,
    QuizResultResponse,
)
from app.services.quiz_service import (
    start_quiz,
    get_next_question,
    submit_answer,
    get_quiz_result,
)

router = APIRouter(prefix="/quiz", tags=["quiz"])
logger = logging.getLogger(__name__)


@router.post("/start", response_model=QuizStartResponse)
async def quiz_start(body: QuizStartRequest):
    """퀴즈 세션 시작 — user_id 없이도 익명 가능"""
    try:
        return await start_quiz(user_id=body.user_id)
    except Exception as e:
        logger.error("[퀴즈] start 오류: %s", e)
        raise HTTPException(status_code=500, detail="퀴즈 시작에 실패했습니다.")


@router.get("/question/{session_id}", response_model=QuizQuestionResponse)
async def quiz_question(
    session_id: str = Path(..., description="퀴즈 세션 ID"),
):
    """다음 문제 가져오기 — Claude가 적응형 난이도로 생성"""
    try:
        return await get_next_question(session_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error("[퀴즈] question 오류: %s | %s", session_id, e)
        raise HTTPException(status_code=500, detail="문제 생성에 실패했습니다.")


@router.post("/answer", response_model=QuizAnswerResponse)
async def quiz_answer(body: QuizAnswerRequest):
    """답변 제출 → 정오 확인 + 난이도 조정 + (완료 시 최종 레벨 반환)"""
    try:
        return await submit_answer(
            session_id=body.session_id,
            question_id=body.question_id,
            answer=body.answer,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("[퀴즈] answer 오류: %s | %s", body.session_id, e)
        raise HTTPException(status_code=500, detail="답변 처리에 실패했습니다.")


@router.get("/result/{session_id}", response_model=QuizResultResponse)
async def quiz_result(
    session_id: str = Path(..., description="퀴즈 세션 ID"),
):
    """최종 레벨 결과 및 전체 답안 조회"""
    try:
        return await get_quiz_result(session_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("[퀴즈] result 오류: %s | %s", session_id, e)
        raise HTTPException(status_code=500, detail="결과 조회에 실패했습니다.")
