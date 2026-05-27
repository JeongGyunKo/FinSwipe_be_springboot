"""새 뉴스 분석 API"""
import logging

from fastapi import APIRouter, HTTPException, Query, Path

from app.schemas.news import (
    NewsAnalyzeRequest,
    EnrichTextResponse,
    TickerSummaryResponse,
)
from app.services.news_service import enrich_article, get_ticker_summary

router = APIRouter(prefix="/news", tags=["news"])
logger = logging.getLogger(__name__)


@router.post("/analyze", response_model=EnrichTextResponse)
async def analyze_article(body: NewsAnalyzeRequest):
    """단일 기사 분석 — 감성, 요약, XAI, 한국어 현지화"""
    try:
        result = await enrich_article(
            news_id=body.source_url,
            title=body.title,
            article_text=body.content,
            summary_text=body.summary,
            tickers=body.tickers,
        )
        return result
    except Exception as e:
        logger.error("[뉴스] analyze 오류: %s", e)
        raise HTTPException(status_code=503, detail="분석 서비스에 일시적인 오류가 발생했습니다.")


@router.get("/summary/{ticker}", response_model=TickerSummaryResponse)
async def ticker_summary(
    ticker: str = Path(..., description="주식 티커 (예: AAPL, TSLA)"),
    level: int = Query(default=3, ge=1, le=5, description="사용자 레벨 (1~5)"),
):
    """티커별 오늘 뉴스 종합 요약 (레벨 맞춤)"""
    try:
        result = await get_ticker_summary(ticker.upper(), level)
        return result
    except Exception as e:
        logger.error("[뉴스] ticker_summary 오류: %s | %s", ticker, e)
        raise HTTPException(status_code=503, detail="요약 서비스에 일시적인 오류가 발생했습니다.")
