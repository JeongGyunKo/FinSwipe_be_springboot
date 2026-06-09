from __future__ import annotations

import asyncio
import logging
import uuid as _uuid_module

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/analysis", tags=["agent"])


# ── 헤드라인 번역 ────────────────────────────────────────────────────────────────

class HeadlineTranslateItem(BaseModel):
    id: str = Field(..., max_length=100)
    headline: str = Field(..., max_length=2000)


class HeadlineTranslateRequest(BaseModel):
    items: list[HeadlineTranslateItem] = Field(..., max_length=30)


class HeadlineTranslateResult(BaseModel):
    id: str
    headline_ko: str | None = None


class HeadlineTranslateResponse(BaseModel):
    results: list[HeadlineTranslateResult]


@router.post("/translate-headlines")
async def translate_headlines(body: HeadlineTranslateRequest) -> HeadlineTranslateResponse:
    try:
        from app.services.translation.headline_batch import translate_headlines_batch
        raw = await asyncio.to_thread(translate_headlines_batch, body.items)
        return HeadlineTranslateResponse(
            results=[HeadlineTranslateResult(**r) for r in raw]
        )
    except Exception as exc:
        logger.error("[헤드라인 번역] 실패: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail="헤드라인 번역 중 오류가 발생했습니다.") from exc


# ── 개인화 분석 에이전트 ──────────────────────────────────────────────────────────

class PersonalizedRequest(BaseModel):
    article_title: str = Field(..., max_length=1000)
    article_text: str = Field(..., max_length=100_000)
    tickers: list[str] = Field(default_factory=list, max_length=50)
    sentiment_label: str = Field(default="neutral", max_length=50)
    sentiment_score: float = 0.0
    sentiment_reason: str = Field(default="", max_length=5000)
    user_level: int = Field(default=3, ge=1, le=5)
    user_tendency: str = Field(default="탐색형", max_length=50)


class PersonalizedResponse(BaseModel):
    personalized_analysis: str | None
    technical_indicators: dict | None
    user_level: int
    user_tendency: str
    error: str | None = None


@router.post("/personalized", response_model=PersonalizedResponse)
async def personalized_analysis(body: PersonalizedRequest) -> PersonalizedResponse:
    from app.services.agent.graph import analysis_graph

    initial_state = {
        "article_title": body.article_title,
        "article_text": body.article_text,
        "tickers": body.tickers,
        "sentiment_label": body.sentiment_label,
        "sentiment_score": body.sentiment_score,
        "sentiment_reason": body.sentiment_reason,
        "user_level": body.user_level,
        "user_tendency": body.user_tendency,
        "price_data": None,
        "technical_indicators": None,
        "personalized_analysis": None,
        "error": None,
    }

    try:
        result = await asyncio.to_thread(analysis_graph.invoke, initial_state)
        return PersonalizedResponse(
            personalized_analysis=result.get("personalized_analysis"),
            technical_indicators=result.get("technical_indicators"),
            user_level=body.user_level,
            user_tendency=body.user_tendency,
            error=result.get("error"),
        )
    except Exception as exc:
        logger.error("[에이전트] 분석 실패: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail="뉴스 분석 중 오류가 발생했습니다.") from exc


class UserIdRequest(BaseModel):
    user_id: str = Field(..., min_length=36, max_length=36)

    @field_validator("user_id")
    @classmethod
    def must_be_uuid(cls, v: str) -> str:
        try:
            _uuid_module.UUID(v)
        except ValueError:
            raise ValueError("user_id는 UUID 형식이어야 합니다")
        return v


# ── 뉴스 큐레이션 에이전트 ─────────────────────────────────────────────────────

@router.post("/curate")
async def curate_news(body: UserIdRequest) -> dict:
    try:
        from app.services.curation.agent import curate_news as _curate
        return await asyncio.to_thread(_curate, body.user_id)
    except Exception as exc:
        logger.error("[큐레이션] 실패: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail="뉴스 큐레이션 중 오류가 발생했습니다.") from exc


# ── 학습 코치 에이전트 ──────────────────────────────────────────────────────────

@router.post("/coach")
async def coach(body: UserIdRequest) -> dict:
    try:
        from app.services.coach.agent import coach as _coach
        return await asyncio.to_thread(_coach, body.user_id)
    except Exception as exc:
        logger.error("[코치] 실패: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail="학습 코치 분석 중 오류가 발생했습니다.") from exc


# ── 티커별 일일 다이제스트 ────────────────────────────────────────────────────────
# 캐시 우선 조회 → 캐시 미스 시 온디맨드 생성으로 폴백
# digest_worker가 백그라운드에서 새 기사 감지 즉시 캐시를 갱신함

@router.post("/digest")
async def daily_digest(body: UserIdRequest) -> dict:
    try:
        from app.services.digest.agent import generate_digest_from_cache
        return await asyncio.to_thread(generate_digest_from_cache, body.user_id)
    except Exception as exc:
        logger.error("[다이제스트] 실패: %s", exc, exc_info=True)
        raise HTTPException(status_code=502, detail="일일 다이제스트 생성 중 오류가 발생했습니다.") from exc
