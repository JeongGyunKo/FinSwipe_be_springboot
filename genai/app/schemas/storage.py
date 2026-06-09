from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import Field, HttpUrl

from app.schemas.article_fetch import ArticleFetchResult
from app.schemas.enrichment import LocalizedArticleContent, SchemaModel
from app.schemas.mixed import (
    ArticleMixedDetectionResult,
    TickerMixedDetectionResult,
)
from app.schemas.sentiment import SentimentResult as FinBERTSentimentResult
from app.schemas.xai import XAIResult


class AnalysisStatus(str, Enum):
    PENDING = "pending"
    FETCH_FAILED = "fetch_failed"
    CLEAN_FAILED = "clean_failed"
    CLEAN_FILTERED = "clean_filtered"
    VALIDATE_FAILED = "validate_failed"
    VALIDATE_FILTERED = "validate_filtered"
    SUMMARIZE_FAILED = "summarize_failed"
    SENTIMENT_FAILED = "sentiment_failed"
    XAI_FAILED = "xai_failed"
    MIXED_DETECTION_FAILED = "mixed_detection_failed"
    BUILD_PAYLOAD_FAILED = "build_payload_failed"
    PERSIST_FAILED = "persist_failed"
    COMPLETED_WITH_PARTIAL_RESULTS = "completed_with_partial_results"
    COMPLETED = "completed"


class AnalysisOutcome(str, Enum):
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FILTERED = "filtered"
    FATAL_FAILURE = "fatal_failure"


class PipelineStageName(str, Enum):
    FETCH = "fetch"
    CLEAN = "clean"
    VALIDATE = "validate"
    SUMMARIZE = "summarize"
    SENTIMENT = "sentiment"
    XAI = "xai"
    MIXED_DETECTION = "mixed_detection"
    BUILD_PAYLOAD = "build_payload"
    PERSIST = "persist"


class PipelineStageStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    FILTERED = "filtered"
    SKIPPED = "skipped"


class PipelineStageResult(SchemaModel):
    stage: PipelineStageName = Field(..., description="Pipeline stage identifier.")
    status: PipelineStageStatus = Field(..., description="Final state for this stage.")
    fatal: bool = Field(
        default=False,
        description="Whether failure at this stage should stop the pipeline.",
    )
    message: str | None = Field(
        default=None,
        description="Useful debug message for success, skip, or failure.",
    )
    started_at: datetime | None = Field(
        default=None,
        description="When execution of the stage started.",
    )
    completed_at: datetime | None = Field(
        default=None,
        description="When execution of the stage finished.",
    )


class StageIOMetric(SchemaModel):
    stage: PipelineStageName = Field(..., description="Pipeline stage identifier.")
    input_chars: int | None = Field(
        default=None,
        ge=0,
        description="Approximate input character count consumed by the stage.",
    )
    output_chars: int | None = Field(
        default=None,
        ge=0,
        description="Approximate output character count produced by the stage.",
    )
    output_items: int | None = Field(
        default=None,
        ge=0,
        description="Optional item count output (for example summary lines or highlights).",
    )
    note: str | None = Field(
        default=None,
        description="Optional stage-specific diagnostic note.",
    )


class StoredSentimentPayload(SchemaModel):
    label: str = Field(..., description="Final sentiment label stored for the article.")
    score: float = Field(..., ge=-100.0, le=100.0)
    confidence: float = Field(..., ge=0.0, le=1.0)
    probabilities: dict[str, float] = Field(
        default_factory=dict,
        description="Class probability map for the stored sentiment result.",
    )


class StoragePayloadError(SchemaModel):
    stage: PipelineStageName = Field(..., description="Pipeline stage related to the issue.")
    message: str = Field(..., min_length=1, description="Stored failure or warning message.")
    fatal: bool = Field(..., description="Whether the issue should be treated as fatal.")


class EnrichmentStoragePayload(SchemaModel):
    news_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    link: HttpUrl = Field(..., description="Canonical article URL.")
    summary_3lines: list[str] = Field(
        default_factory=list,
        description="Three-line article summary when available.",
    )
    sentiment: StoredSentimentPayload | None = Field(
        default=None,
        description="Stored article-level sentiment payload.",
    )
    xai: XAIResult | None = Field(
        default=None,
        description="Stored explainability payload.",
    )
    sentiment_reason: str | None = Field(
        default=None,
        description="Natural language Korean explanation of why this article received its sentiment score.",
    )
    event_category: str | None = Field(
        default=None,
        description="Article event type: earnings, guidance, analyst, product, ma, macro, regulatory, other.",
    )
    sentiment_divergence: bool | None = Field(
        default=None,
        description="True when the title sentiment label differs from the body's dominant sentiment label.",
    )
    localized: LocalizedArticleContent | None = Field(
        default=None,
        description="Stored localized display payload to avoid repeated translation calls.",
    )
    article_mixed: ArticleMixedDetectionResult | None = Field(
        default=None,
        description="Article-level mixed/conflict detection result.",
    )
    ticker_mixed: TickerMixedDetectionResult | None = Field(
        default=None,
        description="Ticker-level mixed/conflict detection result.",
    )
    analysis_status: AnalysisStatus = Field(
        default=AnalysisStatus.PENDING,
        description="Centralized overall pipeline status.",
    )
    analysis_outcome: AnalysisOutcome = Field(
        default=AnalysisOutcome.PARTIAL_SUCCESS,
        description="Top-level outcome separating success, partial success, and fatal failure.",
    )
    pipeline_trace_id: str | None = Field(
        default=None,
        description="Correlation id shared across clean/sentiment/xai/summary/translation logs.",
    )
    failure_code: str | None = Field(
        default=None,
        description=(
            "Stable machine-readable failure code for quick diagnosis. "
            "Can be populated for partial failures as well."
        ),
    )
    analyzed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when this storage payload was assembled.",
    )
    cleaned_text_char_count: int = Field(
        default=0,
        ge=0,
        description="Character count of cleaned article text.",
    )
    cleaned_text_preview: str | None = Field(
        default=None,
        description="Trimmed preview of cleaned article text for debugging.",
    )
    cleaned_text_available: bool = Field(
        default=False,
        description="Whether cleaned article text existed at build time.",
    )
    fetch_result: ArticleFetchResult | None = Field(
        default=None,
        description="Optional fetch trace metadata.",
    )
    stage_statuses: list[PipelineStageResult] = Field(
        default_factory=list,
        description="Per-stage execution details for debugging and observability.",
    )
    stage_io_metrics: list[StageIOMetric] = Field(
        default_factory=list,
        description="Per-stage input/output volume diagnostics.",
    )
    errors: list[StoragePayloadError] = Field(
        default_factory=list,
        description="Fatal and non-fatal issues captured during payload assembly.",
    )


def build_stored_sentiment_payload(
    sentiment_result: FinBERTSentimentResult,
) -> StoredSentimentPayload:
    return StoredSentimentPayload(
        label=sentiment_result.label.value,
        score=sentiment_result.score,
        confidence=sentiment_result.confidence,
        probabilities={
            "positive": sentiment_result.probabilities.positive,
            "neutral": sentiment_result.probabilities.neutral,
            "negative": sentiment_result.probabilities.negative,
        },
    )