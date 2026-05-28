from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.enrichment import ArticleEnrichmentRequest
from app.schemas.storage import (
    AnalysisOutcome,
    AnalysisStatus,
    EnrichmentStoragePayload,
    PipelineStageName,
    PipelineStageResult,
    PipelineStageStatus,
)


def test_article_enrichment_request_normalizes_tickers() -> None:
    payload = ArticleEnrichmentRequest(
        news_id="news-1",
        title="Sample title",
        link="https://example.com/news/1",
        ticker=[" aapl ", "AAPL", "msft "],
    )

    assert payload.ticker == ["AAPL", "MSFT"]


def test_article_enrichment_request_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        ArticleEnrichmentRequest(
            news_id="news-1",
            title="Sample title",
            link="https://example.com/news/1",
            unknown_field="not-allowed",
        )


def test_storage_payload_serializes_stage_statuses() -> None:
    payload = EnrichmentStoragePayload(
        news_id="news-1",
        title="Sample title",
        link="https://example.com/news/1",
        analysis_status=AnalysisStatus.COMPLETED,
        analysis_outcome=AnalysisOutcome.SUCCESS,
        stage_statuses=[
            PipelineStageResult(
                stage=PipelineStageName.FETCH,
                status=PipelineStageStatus.COMPLETED,
                message="Fetched successfully.",
            )
        ],
    )

    dumped = payload.model_dump(mode="json")

    assert dumped["analysis_status"] == "completed"
    assert dumped["stage_statuses"][0]["stage"] == "fetch"
    assert dumped["stage_statuses"][0]["status"] == "completed"


def test_storage_payload_supports_filtered_outcome_and_stage() -> None:
    payload = EnrichmentStoragePayload(
        news_id="news-filtered",
        title="Filtered title",
        link="https://example.com/news-filtered",
        analysis_status=AnalysisStatus.CLEAN_FILTERED,
        analysis_outcome=AnalysisOutcome.FILTERED,
        stage_statuses=[
            PipelineStageResult(
                stage=PipelineStageName.CLEAN,
                status=PipelineStageStatus.FILTERED,
                message="Text cleaning produced no usable article text.",
            )
        ],
    )

    dumped = payload.model_dump(mode="json")

    assert dumped["analysis_status"] == "clean_filtered"
    assert dumped["analysis_outcome"] == "filtered"
    assert dumped["stage_statuses"][0]["status"] == "filtered"