from fastapi import APIRouter

from app.schemas.enrichment import (
    ArticleEnrichmentResponse,
    DirectTextEnrichmentRequest,
    FlexibleTextEnrichmentRequest,
)
from app.services.enrichment_service import EnrichmentService


router = APIRouter(tags=["enrichment"])
service = EnrichmentService()


@router.post(
    "/articles/enrich",
    response_model=ArticleEnrichmentResponse,
    summary="Run enrichment immediately and return the final result",
)
async def enrich_article(
    payload: FlexibleTextEnrichmentRequest,
) -> ArticleEnrichmentResponse:
    return await service.enrich_article(payload)


@router.post(
    "/articles/enrich-text",
    response_model=ArticleEnrichmentResponse,
    summary="Run direct-text enrichment immediately and return the final result",
)
async def enrich_article_text(
    payload: DirectTextEnrichmentRequest,
) -> ArticleEnrichmentResponse:
    return await service.enrich_article_text(payload)