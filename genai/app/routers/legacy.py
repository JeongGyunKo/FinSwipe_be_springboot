"""Spring Boot AnalyzerService 호환 엔드포인트 — 기존 /api/v1/articles/enrich-text"""
import logging

from fastapi import APIRouter, HTTPException
from app.schemas.news import EnrichTextRequest, EnrichTextResponse
from app.services.news_service import enrich_article

router = APIRouter(prefix="/api/v1/articles", tags=["legacy"])
logger = logging.getLogger(__name__)


@router.post("/enrich-text")
async def enrich_text(body: EnrichTextRequest) -> dict:
    """
    Spring Boot AnalyzerService.enrichSingle() 호출 대상.

    요청: {news_id, title, link, article_text, summary_text?, ticker?}
    응답: {outcome, sentiment:{label, score}, summary_3lines, xai, localized:{title, summary_3lines, xai}}
    """
    try:
        result = await enrich_article(
            news_id=body.news_id,
            title=body.title or "",
            article_text=body.article_text,
            summary_text=body.summary_text,
            tickers=body.tickers,
        )
        return result
    except Exception as e:
        logger.error("[레거시] enrich-text 오류: %s | %s", body.news_id[:60], e)
        # Spring Boot가 503을 받으면 unavailable 처리 → 상세 오류는 로그로만
        raise HTTPException(status_code=503, detail=str(e))
