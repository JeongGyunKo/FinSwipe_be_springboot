from __future__ import annotations

from enum import Enum

from pydantic import Field, model_validator

from app.schemas.enrichment import SchemaModel


class FinBERTSentimentLabel(str, Enum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class AggregationStrategy(str, Enum):
    MEAN = "mean"
    WEIGHTED_MEAN = "weighted_mean"


class SentimentChunkSource(str, Enum):
    TITLE = "title"
    BODY = "body"


class SentimentProbabilities(SchemaModel):
    positive: float = Field(..., ge=0.0, le=1.0)
    neutral: float = Field(..., ge=0.0, le=1.0)
    negative: float = Field(..., ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_total_probability(self) -> SentimentProbabilities:
        total = self.positive + self.neutral + self.negative
        if not 0.99 <= total <= 1.01:
            raise ValueError("Sentiment probabilities must sum to approximately 1.0")
        return self


class ChunkSentimentResult(SchemaModel):
    chunk_index: int = Field(..., ge=0, description="0-based chunk index.")
    source: SentimentChunkSource = Field(
        ...,
        description="Whether this chunk came from the title or article body.",
    )
    text: str = Field(..., min_length=1, description="Chunk text scored by the model.")
    token_count: int = Field(..., ge=1, description="Estimated token count for the chunk.")
    weight: float = Field(..., ge=0.0, description="Aggregation weight for this chunk.")
    label: FinBERTSentimentLabel = Field(..., description="Chunk-level sentiment label.")
    score: float = Field(..., ge=-100.0, le=100.0)
    confidence: float = Field(..., ge=0.0, le=1.0)
    probabilities: SentimentProbabilities = Field(
        ...,
        description="Raw class probabilities for this chunk.",
    )


class SentimentResult(SchemaModel):
    label: FinBERTSentimentLabel = Field(
        ...,
        description="Dominant FinBERT sentiment label.",
    )
    score: float = Field(
        ...,
        ge=-100.0,
        le=100.0,
        description="Continuous sentiment score derived from aggregated probabilities.",
    )
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence for the dominant class.",
    )
    probabilities: SentimentProbabilities = Field(
        ...,
        description="Raw aggregated probabilities for each FinBERT class.",
    )
    aggregation_strategy: AggregationStrategy = Field(
        default=AggregationStrategy.WEIGHTED_MEAN,
        description="Strategy used to combine chunk-level predictions.",
    )
    chunk_results: list[ChunkSentimentResult] = Field(
        default_factory=list,
        description="Per-chunk sentiment outputs used to build the article result.",
    )
    disagreement_ratio: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Weighted share of chunks that disagree with the final article label.",
    )
    chunk_count: int = Field(
        default=0,
        ge=0,
        description="Number of chunk-level predictions included in aggregation.",
    )

    @model_validator(mode="after")
    def validate_chunk_count(self) -> SentimentResult:
        if self.chunk_results and self.chunk_count != len(self.chunk_results):
            raise ValueError("chunk_count must match the number of chunk_results")
        return self