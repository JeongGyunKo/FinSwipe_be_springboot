from __future__ import annotations

from app.schemas.sentiment import (
    ChunkSentimentResult,
    FinBERTSentimentLabel,
    SentimentChunkSource,
    SentimentProbabilities,
)
from app.services.sentiment.finbert import analyze_sentiment


def test_analyze_sentiment_returns_expected_structure(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.sentiment.finbert._get_finbert_components",
        lambda: (object(), object()),
    )
    monkeypatch.setattr(
        "app.services.sentiment.finbert._predict_chunks",
        lambda **kwargs: [
            ChunkSentimentResult(
                chunk_index=0,
                source=SentimentChunkSource.TITLE,
                text="Title chunk",
                token_count=10,
                weight=1.2,
                label=FinBERTSentimentLabel.POSITIVE,
                score=52.0,
                confidence=0.81,
                probabilities=SentimentProbabilities(
                    positive=0.76,
                    neutral=0.18,
                    negative=0.06,
                ),
            ),
            ChunkSentimentResult(
                chunk_index=1,
                source=SentimentChunkSource.BODY,
                text="Body chunk",
                token_count=40,
                weight=1.0,
                label=FinBERTSentimentLabel.POSITIVE,
                score=48.0,
                confidence=0.79,
                probabilities=SentimentProbabilities(
                    positive=0.74,
                    neutral=0.2,
                    negative=0.06,
                ),
            ),
        ],
    )

    result = analyze_sentiment(
        title="Positive quarterly update",
        article_text="Revenue improved and margins expanded.",
    )

    assert result.label == FinBERTSentimentLabel.POSITIVE
    assert -100.0 <= result.score <= 100.0
    assert 0.0 <= result.confidence <= 1.0
    assert result.chunk_count == 2
    assert len(result.chunk_results) == 2
    assert result.probabilities.positive > result.probabilities.negative