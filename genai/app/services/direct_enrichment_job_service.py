from __future__ import annotations

import asyncio
from time import monotonic

from fastapi import HTTPException

from app.repositories import EnrichmentRepository, create_repository
from app.schemas.enrichment import FlexibleTextEnrichmentRequest
from app.schemas.ingestion import EnrichmentJobStatus
from app.schemas.storage import EnrichmentStoragePayload


class DirectEnrichmentJobService:
    """Submit direct enrichment work as a job and wait for the stored result."""

    def __init__(
        self,
        repository: EnrichmentRepository | None = None,
        *,
        wait_timeout_seconds: float,
        poll_interval_seconds: float,
    ) -> None:
        self._repository = repository
        self._wait_timeout_seconds = wait_timeout_seconds
        self._poll_interval_seconds = poll_interval_seconds

    @property
    def repository(self) -> EnrichmentRepository:
        if self._repository is None:
            self._repository = create_repository()
        return self._repository

    async def submit_and_wait(
        self,
        payload: FlexibleTextEnrichmentRequest,
    ) -> EnrichmentStoragePayload:
        await asyncio.to_thread(self.repository.upsert_raw_news, payload)

        active_job = await asyncio.to_thread(self.repository.get_active_job, payload.news_id)
        if active_job is not None:
            awaited_job_id = active_job.job_id
        else:
            created_job = await asyncio.to_thread(
                self.repository.create_enrichment_job,
                payload.news_id,
            )
            awaited_job_id = created_job.job_id

        deadline = monotonic() + self._wait_timeout_seconds
        while monotonic() < deadline:
            _, latest_job, enrichment = await asyncio.to_thread(
                self.repository.get_news_snapshot,
                payload.news_id,
            )

            if latest_job is None or latest_job.job_id != awaited_job_id:
                await asyncio.sleep(self._poll_interval_seconds)
                continue

            if latest_job.status in {
                EnrichmentJobStatus.COMPLETED,
                EnrichmentJobStatus.FAILED,
            }:
                if enrichment is not None:
                    return enrichment
                raise HTTPException(
                    status_code=500,
                    detail=latest_job.last_error
                    or "Worker finished the enrichment job without a stored result.",
                )

            await asyncio.sleep(self._poll_interval_seconds)

        raise HTTPException(
            status_code=503,
            detail=(
                "Timed out waiting for the worker to complete the direct enrichment request. "
                "The job is still queued or processing."
            ),
        )