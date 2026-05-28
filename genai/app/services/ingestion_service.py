from __future__ import annotations

import asyncio

from app.repositories import EnrichmentRepository, create_repository
from app.schemas.ingestion import (
    DirectTextIngestionRequest,
    IngestionAcceptedResponse,
    NewsResultResponse,
    NewsProcessingStatusResponse,
    RawNewsIngestionRequest,
)
from app.schemas.operations import OperationalStatsResponse
from app.schemas.storage import AnalysisOutcome, AnalysisStatus
from app.services.enrichment_service import build_api_enrichment_response
from app.services.response_state import derive_error_code, derive_processing_state, map_job_status_to_processing_state


class IngestionService:
    """Coordinate raw-news intake plus read/query flows for the web layer."""

    def __init__(
        self,
        repository: EnrichmentRepository | None = None,
    ) -> None:
        self._repository = repository

    @property
    def repository(self) -> EnrichmentRepository:
        if self._repository is None:
            self._repository = create_repository()
        return self._repository

    async def ingest_article(
        self,
        payload: RawNewsIngestionRequest,
    ) -> IngestionAcceptedResponse:
        return await self._ingest_payload(payload)

    async def ingest_article_text(
        self,
        payload: DirectTextIngestionRequest,
    ) -> IngestionAcceptedResponse:
        return await self._ingest_payload(payload)

    async def _ingest_payload(
        self,
        payload: RawNewsIngestionRequest,
    ) -> IngestionAcceptedResponse:
        existing = await asyncio.to_thread(self.repository.get_enrichment_result, payload.news_id)
        if (
            existing is not None
            and existing.analysis_status == AnalysisStatus.COMPLETED
            and existing.analysis_outcome == AnalysisOutcome.SUCCESS
            and _normalize_link(existing.link) == _normalize_link(payload.link)
        ):
            latest_job = await asyncio.to_thread(self.repository.get_latest_job, payload.news_id)
            return IngestionAcceptedResponse(
                news_id=payload.news_id,
                queued=False,
                processing_state=derive_processing_state(
                    latest_job=latest_job,
                    enrichment=existing,
                ),
                error_code=derive_error_code(latest_job=latest_job, enrichment=existing),
                message="Existing completed enrichment result reused; no new job queued.",
                job=latest_job,
            )

        await asyncio.to_thread(self.repository.upsert_raw_news, payload)

        active_job = await asyncio.to_thread(self.repository.get_active_job, payload.news_id)
        if active_job is not None:
            return IngestionAcceptedResponse(
                news_id=payload.news_id,
                queued=False,
                processing_state=map_job_status_to_processing_state(active_job.status),
                error_code=derive_error_code(latest_job=active_job, enrichment=None),
                message="An enrichment job is already queued or processing for this article.",
                job=active_job,
            )

        job = await asyncio.to_thread(self.repository.create_enrichment_job, payload.news_id)
        return IngestionAcceptedResponse(
            news_id=payload.news_id,
            queued=True,
            processing_state=map_job_status_to_processing_state(job.status),
            error_code=None,
            message="Raw news metadata saved and enrichment job queued.",
            job=job,
        )

    async def get_news_status(self, news_id: str) -> NewsProcessingStatusResponse | None:
        raw_news, latest_job, enrichment = await asyncio.to_thread(
            self.repository.get_news_snapshot,
            news_id,
        )

        if raw_news is None and latest_job is None and enrichment is None:
            return None

        return NewsProcessingStatusResponse(
            news_id=news_id,
            processing_state=derive_processing_state(
                latest_job=latest_job,
                enrichment=enrichment,
            ),
            error_code=derive_error_code(latest_job=latest_job, enrichment=enrichment),
            raw_news=raw_news,
            latest_job=latest_job,
            enrichment=enrichment,
        )

    async def get_news_result(self, news_id: str) -> NewsResultResponse | None:
        raw_news, latest_job, enrichment = await asyncio.to_thread(
            self.repository.get_news_snapshot,
            news_id,
        )

        if raw_news is None and latest_job is None and enrichment is None:
            return None

        return NewsResultResponse(
            news_id=news_id,
            processing_state=derive_processing_state(
                latest_job=latest_job,
                enrichment=enrichment,
            ),
            error_code=derive_error_code(latest_job=latest_job, enrichment=enrichment),
            raw_news=raw_news,
            latest_job=latest_job,
            result=build_api_enrichment_response(enrichment) if enrichment is not None else None,
        )

    async def get_operational_stats(self) -> OperationalStatsResponse:
        return await asyncio.to_thread(self.repository.get_operational_stats)


def _normalize_link(value: object) -> str:
    return str(value).strip().rstrip("/")