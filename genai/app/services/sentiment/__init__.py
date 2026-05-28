"""FinBERT-powered sentiment analysis for financial news."""

from app.services.sentiment.chunking import (
    aggregate_chunk_results,
    build_chunk_sentiment_result,
    chunk_article_text,
)


def analyze_sentiment(*args, **kwargs):
    from app.services.sentiment.finbert import analyze_sentiment as _analyze_sentiment

    return _analyze_sentiment(*args, **kwargs)


def predict_text_probabilities(*args, **kwargs):
    from app.services.sentiment.finbert import (
        predict_text_probabilities as _predict_text_probabilities,
    )

    return _predict_text_probabilities(*args, **kwargs)


def score_text_with_attentions(*args, **kwargs):
    from app.services.sentiment.finbert import (
        score_text_with_attentions as _score_text_with_attentions,
    )

    return _score_text_with_attentions(*args, **kwargs)

__all__ = [
    "aggregate_chunk_results",
    "analyze_sentiment",
    "build_chunk_sentiment_result",
    "chunk_article_text",
    "predict_text_probabilities",
    "score_text_with_attentions",
]