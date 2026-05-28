import asyncio

from fastapi import APIRouter, HTTPException

from app.core import get_settings
from app.schemas.ingestion import (
    DirectTextIngestionRequest,
    IngestionAcceptedResponse,
    NewsResultResponse,
    NewsProcessingStatusResponse,
    RawNewsIngestionRequest,
    WorkerProcessResponse,
)
from app.schemas.operations import OperationalStatsResponse
from app.services.ingestion_service import IngestionService
from app.services.job_processing_service import JobProcessingService


router = APIRouter(tags=["ingestion"])
service = IngestionService()
job_service = JobProcessingService()
settings = get_settings()


@router.post(
    "/news/intake",
    response_model=IngestionAcceptedResponse,
    summary="Store raw news metadata and queue enrichment",
)
async def ingest_raw_news(
    payload: RawNewsIngestionRequest,
) -> IngestionAcceptedResponse:
    return await service.ingest_article(payload)


@router.post(
    "/news/intake-text",
    response_model=IngestionAcceptedResponse,
    summary="Store licensed article or summary text and queue enrichment",
)
async def ingest_raw_news_text(
    payload: DirectTextIngestionRequest,
) -> IngestionAcceptedResponse:
    return await service.ingest_article_text(payload)


@router.get(
    "/operations/stats",
    response_model=OperationalStatsResponse,
    summary="Get operational metrics for jobs and fetch failures",
)
async def get_operational_stats() -> OperationalStatsResponse:
    return await service.get_operational_stats()


@router.get(
    "/news/{news_id:path}/result",
    response_model=NewsResultResponse,
    summary="Get backend-friendly enrichment result for a news item",
)
async def get_news_result(news_id: str) -> NewsResultResponse:
    result = await service.get_news_result(news_id)
    if result is None:
        raise HTTPException(status_code=404, detail="News item not found.")
    return result


@router.get(
    "/news/{news_id:path}",
    response_model=NewsProcessingStatusResponse,
    summary="Get raw news, latest job, and enrichment result",
)
async def get_news_status(news_id: str) -> NewsProcessingStatusResponse:
    result = await service.get_news_status(news_id)
    if result is None:
        raise HTTPException(status_code=404, detail="News item not found.")
    return result


@router.post(
    "/jobs/process-next",
    response_model=WorkerProcessResponse,
    summary="Process the next queued enrichment job",
)
async def process_next_job() -> WorkerProcessResponse:
    if not settings.enable_job_process_api:
        raise HTTPException(
            status_code=503,
            detail=(
                "Job processing API is disabled on this web service instance. "
                "Run the dedicated worker service instead."
            ),
        )
    return await asyncio.to_thread(job_service.process_next_job)