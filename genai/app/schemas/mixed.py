from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum

from pydantic import Field, field_validator

from app.schemas.enrichment import SchemaModel
from app.schemas.sentiment import FinBERTSentimentLabel


class ArticleMixedReasonCode(str, Enum):
    LOW_CONFIDENCE = "low_confidence"
    SMALL_SCORE_GAP = "small_score_gap"
    CHUNK_DISAGREEMENT = "chunk_disagreement"


class TickerMixedReasonCode(str, Enum):
    HIGH_SCORE_VARIANCE = "high_score_variance"
    CONFLICTING_DISTRIBUTION = "conflicting_distribution"
    SPARSE_DATA = "sparse_data"


class MixedStatus(str, Enum):
    CLEAR = "clear"
    MIXED = "mixed"
    INSUFFICIENT_DATA = "insufficient_data"


class MixedReason(SchemaModel):
    code: ArticleMixedReasonCode | TickerMixedReasonCode = Field(
        ...,
        description="Machine-readable reason code for the mixed/conflict decision.",
    )
    triggered: bool = Field(..., description="Whether the rule triggered.")
    value: float | None = Field(
        default=None,
        description="Observed metric value used by the rule.",
    )
    threshold: float | None = Field(
        default=None,
        description="Threshold used for the rule evaluation.",
    )
    message: str = Field(..., description="Human-readable explanation of the rule outcome.")


class ArticleMixedConfig(SchemaModel):
    confidence_threshold: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        description="Confidence below this threshold contributes to mixed classification.",
    )
    absolute_score_threshold: float = Field(
        default=20.0,
        ge=0.0,
        le=100.0,
        description="Absolute sentiment score below this threshold contributes to mixed classification.",
    )
    disagreement_ratio_threshold: float = Field(
        default=0.35,
        ge=0.0,
        le=1.0,
        description="Chunk disagreement ratio above this threshold contributes to mixed classification.",
    )
    min_trigger_count: int = Field(
        default=2,
        ge=1,
        description="Minimum number of triggered rules required to mark the article as mixed.",
    )


class ArticleMixedDetectionResult(SchemaModel):
    status: MixedStatus = Field(..., description="Overall article-level mixed status.")
    is_mixed: bool = Field(..., description="Whether the article is mixed.")
    has_conflicting_signals: bool = Field(
        ...,
        description="Whether chunk-level signals conflict meaningfully.",
    )
    dominant_sentiment: FinBERTSentimentLabel | None = Field(
        default=None,
        description="Dominant article sentiment if one remains identifiable.",
    )
    score: float = Field(..., ge=-100.0, le=100.0)
    confidence: float = Field(..., ge=0.0, le=1.0)
    disagreement_ratio: float = Field(..., ge=0.0, le=1.0)
    triggered_reason_codes: list[ArticleMixedReasonCode] = Field(default_factory=list)
    reasons: list[MixedReason] = Field(default_factory=list)
    thresholds: ArticleMixedConfig = Field(..., description="Thresholds used for evaluation.")


class TickerSentimentObservation(SchemaModel):
    ticker: str = Field(..., min_length=1, description="Ticker symbol for the article.")
    news_id: str = Field(..., min_length=1, description="Unique article identifier.")
    score: float = Field(..., ge=-100.0, le=100.0)
    label: FinBERTSentimentLabel = Field(..., description="Article-level sentiment label.")
    confidence: float = Field(..., ge=0.0, le=1.0)
    analyzed_at: datetime = Field(..., description="When the article sentiment was analyzed.")

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("analyzed_at")
    @classmethod
    def normalize_analyzed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class TickerSentimentDistribution(SchemaModel):
    positive_count: int = Field(default=0, ge=0)
    neutral_count: int = Field(default=0, ge=0)
    negative_count: int = Field(default=0, ge=0)

    @property
    def total_count(self) -> int:
        return self.positive_count + self.neutral_count + self.negative_count


class TickerMixedConfig(SchemaModel):
    lookback_hours: int = Field(
        default=72,
        ge=1,
        description="Only articles within this recent window are considered.",
    )
    min_articles: int = Field(
        default=3,
        ge=1,
        description="Minimum article count required for ticker-level mixed evaluation.",
    )
    score_stddev_threshold: float = Field(
        default=35.0,
        ge=0.0,
        le=100.0,
        description="Score standard deviation above this threshold contributes to mixed classification.",
    )
    opposing_side_ratio_threshold: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        description="Minimum share required on both positive and negative sides to treat distribution as conflicting.",
    )
    min_trigger_count: int = Field(
        default=2,
        ge=1,
        description="Minimum number of triggered rules required to mark the ticker as mixed.",
    )


class TickerMixedDetectionResult(SchemaModel):
    ticker: str = Field(..., min_length=1)
    status: MixedStatus = Field(..., description="Overall ticker-level mixed status.")
    is_mixed: bool = Field(..., description="Whether the ticker sentiment is mixed.")
    article_count: int = Field(..., ge=0, description="Recent article count used in evaluation.")
    lookback_start: datetime | None = Field(
        default=None,
        description="Start of the recent analysis window.",
    )
    lookback_end: datetime | None = Field(
        default=None,
        description="End of the recent analysis window.",
    )
    mean_score: float | None = Field(default=None, ge=-100.0, le=100.0)
    score_stddev: float | None = Field(default=None, ge=0.0)
    sentiment_distribution: TickerSentimentDistribution = Field(
        ...,
        description="Counts of recent article sentiment labels.",
    )
    positive_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    negative_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    triggered_reason_codes: list[TickerMixedReasonCode] = Field(default_factory=list)
    reasons: list[MixedReason] = Field(default_factory=list)
    thresholds: TickerMixedConfig = Field(..., description="Thresholds used for evaluation.")
    recent_articles: list[TickerSentimentObservation] = Field(
        default_factory=list,
        description="Articles included in the ticker-level evaluation window.",
    )

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str) -> str:
        return value.strip().upper()


def compute_lookback_start(
    *,
    reference_time: datetime,
    lookback_hours: int,
) -> datetime:
    normalized_reference = reference_time.astimezone(timezone.utc)
    return normalized_reference - timedelta(hours=lookback_hours)