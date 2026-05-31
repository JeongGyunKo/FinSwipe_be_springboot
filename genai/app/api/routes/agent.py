from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/analysis", tags=["agent"])


class PersonalizedRequest(BaseModel):
    article_title: str
    article_text: str
    tickers: list[str] = Field(default_factory=list)
    sentiment_label: str = "neutral"
    sentiment_score: float = 0.0
    sentiment_reason: str = ""
    user_level: int = Field(default=3, ge=1, le=5)
    user_tendency: str = "탐색형"


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
        logger.error("[에이전트] 분석 실패: %s", exc)
        raise HTTPException(status_code=502, detail=f"분석 실패: {exc}") from exc
