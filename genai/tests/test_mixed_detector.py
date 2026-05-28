from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.schemas.mixed import TickerSentimentObservation
from app.schemas.sentiment import (
    AggregationStrategy,
    ChunkSentimentResult,
    FinBERTSentimentLabel,
    SentimentChunkSource,
    SentimentProbabilities,
    SentimentResult,
)
from app.services.mixed_detector import (
    detect_article_level_mixed,
    detect_ticker_level_mixed,
)


def test_article_level_mixed_detection_triggers_on_low_confidence_and_disagreement() -> None:
    sentiment_result = SentimentResult(
        label=FinBERTSentimentLabel.NEUTRAL,
        score=8.0,
        confidence=0.42,
        probabilities=SentimentProbabilities(
            positive=0.34,
            neutral=0.33,
            negative=0.33,
        ),
        aggregation_strategy=AggregationStrategy.WEIGHTED_MEAN,
        chunk_results=[
            ChunkSentimentResult(
                chunk_index=0,
                source=SentimentChunkSource.BODY,
                text="Positive signal",
                token_count=20,
                weight=1.0,
                label=FinBERTSentimentLabel.POSITIVE,
                score=45.0,
                confidence=0.8,
                probabilities=SentimentProbabilities(
                    positive=0.7,
                    neutral=0.2,
                    negative=0.1,
                ),
            )
        ],
        disagreement_ratio=0.5,
        chunk_count=1,
    )

    result = detect_article_level_mixed(sentiment_result)

    assert result.is_mixed is True
    assert "low_confidence" in [code.value for code in result.triggered_reason_codes]
    assert "chunk_disagreement" in [code.value for code in result.triggered_reason_codes]


def test_ticker_level_mixed_detection_triggers_on_variance_and_conflicting_distribution() -> None:
    now = datetime.now(timezone.utc)
    recent_articles = [
        TickerSentimentObservation(
            ticker="AAPL",
            news_id="1",
            score=78.0,
            label=FinBERTSentimentLabel.POSITIVE,
            confidence=0.9,
            analyzed_at=now - timedelta(hours=2),
        ),
        TickerSentimentObservation(
            ticker="AAPL",
            news_id="2",
            score=-72.0,
            label=FinBERTSentimentLabel.NEGATIVE,
            confidence=0.88,
            analyzed_at=now - timedelta(hours=4),
        ),
        TickerSentimentObservation(
            ticker="AAPL",
            news_id="3",
            score=64.0,
            label=FinBERTSentimentLabel.POSITIVE,
            confidence=0.83,
            analyzed_at=now - timedelta(hours=6),
        ),
        TickerSentimentObservation(
            ticker="AAPL",
            news_id="4",
            score=-58.0,
            label=FinBERTSentimentLabel.NEGATIVE,
            confidence=0.81,
            analyzed_at=now - timedelta(hours=8),
        ),
    ]

    result = detect_ticker_level_mixed(
        ticker="AAPL",
        recent_articles=recent_articles,
        reference_time=now,
    )

    assert result.is_mixed is True
    assert result.article_count == 4
    assert "high_score_variance" in [code.value for code in result.triggered_reason_codes]
    assert "conflicting_distribution" in [code.value for code in result.triggered_reason_codes]


def test_ticker_level_mixed_detection_stays_clear_when_only_one_rule_triggers() -> None:
    now = datetime.now(timezone.utc)
    recent_articles = [
        TickerSentimentObservation(
            ticker="AAPL",
            news_id="1",
            score=24.0,
            label=FinBERTSentimentLabel.POSITIVE,
            confidence=0.9,
            analyzed_at=now - timedelta(hours=2),
        ),
        TickerSentimentObservation(
            ticker="AAPL",
            news_id="2",
            score=19.0,
            label=FinBERTSentimentLabel.POSITIVE,
            confidence=0.88,
            analyzed_at=now - timedelta(hours=4),
        ),
        TickerSentimentObservation(
            ticker="AAPL",
            news_id="3",
            score=-8.0,
            label=FinBERTSentimentLabel.NEGATIVE,
            confidence=0.81,
            analyzed_at=now - timedelta(hours=6),
        ),
        TickerSentimentObservation(
            ticker="AAPL",
            news_id="4",
            score=21.0,
            label=FinBERTSentimentLabel.POSITIVE,
            confidence=0.84,
            analyzed_at=now - timedelta(hours=8),
        ),
    ]

    result = detect_ticker_level_mixed(
        ticker="AAPL",
        recent_articles=recent_articles,
        reference_time=now,
    )

    assert result.is_mixed is False
    assert result.status.value == "clear"
    assert "conflicting_distribution" in [code.value for code in result.triggered_reason_codes]
    assert "high_score_variance" not in [code.value for code in result.triggered_reason_codes]