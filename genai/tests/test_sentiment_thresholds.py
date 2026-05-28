from __future__ import annotations

from app.schemas.sentiment import (
    AggregationStrategy,
    FinBERTSentimentLabel,
    SentimentChunkSource,
    SentimentProbabilities,
)
from app.services.sentiment.chunking import (
    aggregate_chunk_results,
    build_chunk_sentiment_result,
)


def test_chunk_label_uses_score_thresholds_for_neutral_band() -> None:
    result = build_chunk_sentiment_result(
        chunk_index=0,
        source=SentimentChunkSource.BODY,
        text="Mixed guidance with both upside and downside factors.",
        token_count=12,
        weight=1.0,
        probabilities=SentimentProbabilities(
            positive=0.46,
            neutral=0.14,
            negative=0.40,
        ),
        positive_score_threshold=8.0,
        negative_score_threshold=-8.0,
    )

    assert result.score == 6.0
    assert result.label == FinBERTSentimentLabel.NEUTRAL


def test_aggregate_label_uses_score_thresholds_for_neutral_band() -> None:
    chunks = [
        build_chunk_sentiment_result(
            chunk_index=0,
            source=SentimentChunkSource.BODY,
            text="Results were mixed with limited visibility.",
            token_count=10,
            weight=1.0,
            probabilities=SentimentProbabilities(
                positive=0.47,
                neutral=0.12,
                negative=0.41,
            ),
            positive_score_threshold=8.0,
            negative_score_threshold=-8.0,
        ),
        build_chunk_sentiment_result(
            chunk_index=1,
            source=SentimentChunkSource.BODY,
            text="Management reiterated cautious guidance.",
            token_count=10,
            weight=1.0,
            probabilities=SentimentProbabilities(
                positive=0.45,
                neutral=0.15,
                negative=0.40,
            ),
            positive_score_threshold=8.0,
            negative_score_threshold=-8.0,
        ),
    ]

    result = aggregate_chunk_results(
        chunks,
        strategy=AggregationStrategy.WEIGHTED_MEAN,
        positive_score_threshold=8.0,
        negative_score_threshold=-8.0,
    )

    assert -8.0 < result.score < 8.0
    assert result.label == FinBERTSentimentLabel.NEUTRAL