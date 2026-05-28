from __future__ import annotations

import time
from dataclasses import replace

import pytest
from fastapi import HTTPException

from app.repositories import InMemoryEnrichmentRepository
from app.schemas.enrichment import DirectTextEnrichmentRequest
from app.services import enrichment_service as enrichment_service_module


@pytest.mark.anyio
async def test_enrich_article_text_returns_504_when_pipeline_times_out(monkeypatch) -> None:
    service = enrichment_service_module.EnrichmentService(
        repository=InMemoryEnrichmentRepository()
    )
    monkeypatch.setattr(
        enrichment_service_module,
        "settings",
        replace(
            enrichment_service_module.settings,
            use_worker_backed_direct_enrichment=False,
            pipeline_timeout_seconds=0.01,
        ),
    )

    async def _no_reuse(_payload):
        return None

    monkeypatch.setattr(service, "_get_reusable_completed_result", _no_reuse)

    def _slow_run_with_text(*_args, **_kwargs):
        time.sleep(0.2)
        raise AssertionError("Timeout guard should fire before this returns.")

    monkeypatch.setattr(service.orchestrator, "run_with_text", _slow_run_with_text)

    payload = DirectTextEnrichmentRequest(
        news_id="timeout-news-1",
        title="Timeout simulation",
        link="https://example.com/articles/timeout-news-1",
        ticker=["AAPL"],
        source="unit-test",
        article_text="This is a test article body.",
        summary_text=None,
    )

    with pytest.raises(HTTPException) as exc_info:
        await service.enrich_article_text(payload)

    assert exc_info.value.status_code == 504
    assert "timed out" in str(exc_info.value.detail).lower()