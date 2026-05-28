from __future__ import annotations

from types import SimpleNamespace

from app.schemas.sentiment import (
    AggregationStrategy,
    ChunkSentimentResult,
    FinBERTSentimentLabel,
    SentimentChunkSource,
    SentimentProbabilities,
    SentimentResult,
)
from app.services.sentiment.finbert import AttentionTokenScore
from app.services.xai.attention_explainer import explain_sentiment


def test_attention_explainer_builds_sentence_highlights_from_attention(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.xai.attention_explainer.analyze_sentiment",
        lambda title, article_text: SentimentResult(
            label=FinBERTSentimentLabel.POSITIVE,
            score=44.0,
            confidence=0.81,
            probabilities=SentimentProbabilities(
                positive=0.7,
                neutral=0.2,
                negative=0.1,
            ),
            aggregation_strategy=AggregationStrategy.WEIGHTED_MEAN,
            chunk_results=[],
            disagreement_ratio=0.0,
            chunk_count=0,
        ),
    )
    monkeypatch.setattr(
        "app.services.xai.attention_explainer.score_text_with_attentions",
        lambda text: SimpleNamespace(
            truncated=False,
            token_scores=[
                AttentionTokenScore(
                    token="Revenue",
                    start_char=0,
                    end_char=7,
                    attention_weight=0.9,
                ),
                AttentionTokenScore(
                    token="Margins",
                    start_char=14,
                    end_char=21,
                    attention_weight=0.4,
                ),
                AttentionTokenScore(
                    token="Outlook",
                    start_char=32,
                    end_char=39,
                    attention_weight=0.2,
                ),
            ],
        ),
    )

    result = explain_sentiment(
        title="",
        article_text="Revenue rose. Margins improved. Outlook stayed firm.",
    )

    assert result.explanation_method == "attention_sentence"
    assert result.highlights
    assert result.highlights[0].text_snippet == "Revenue rose."
    assert result.highlights[0].start_char == 0
    assert result.highlights[0].end_char == len("Revenue rose.")
    assert result.highlights[0].importance_score >= result.highlights[1].importance_score


def test_attention_explainer_adjusts_offsets_when_title_is_present(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.xai.attention_explainer.analyze_sentiment",
        lambda title, article_text: SentimentResult(
            label=FinBERTSentimentLabel.NEGATIVE,
            score=-31.0,
            confidence=0.74,
            probabilities=SentimentProbabilities(
                positive=0.1,
                neutral=0.25,
                negative=0.65,
            ),
            aggregation_strategy=AggregationStrategy.WEIGHTED_MEAN,
            chunk_results=[],
            disagreement_ratio=0.0,
            chunk_count=0,
        ),
    )
    title = "Acme slips on weak quarter"
    body = "Revenue fell sharply. Margins compressed."
    body_offset = len(title) + 2

    monkeypatch.setattr(
        "app.services.xai.attention_explainer.score_text_with_attentions",
        lambda text: SimpleNamespace(
            truncated=False,
            token_scores=[
                AttentionTokenScore(
                    token="Revenue",
                    start_char=body_offset,
                    end_char=body_offset + 7,
                    attention_weight=0.8,
                ),
                AttentionTokenScore(
                    token="Margins",
                    start_char=body_offset + 22,
                    end_char=body_offset + 29,
                    attention_weight=0.3,
                ),
            ],
        ),
    )

    result = explain_sentiment(title=title, article_text=body)

    assert result.highlights
    assert result.highlights[0].start_char == 0
    assert result.highlights[0].text_snippet == "Revenue fell sharply."


def test_attention_explainer_reuses_provided_sentiment_result(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.xai.attention_explainer.analyze_sentiment",
        lambda title, article_text: (_ for _ in ()).throw(
            AssertionError("Provided sentiment_result should be reused.")
        ),
    )
    monkeypatch.setattr(
        "app.services.xai.attention_explainer.score_text_with_attentions",
        lambda text: SimpleNamespace(
            truncated=False,
            token_scores=[
                AttentionTokenScore(
                    token="Revenue",
                    start_char=0,
                    end_char=7,
                    attention_weight=0.9,
                ),
            ],
        ),
    )
    sentiment_result = SentimentResult(
        label=FinBERTSentimentLabel.POSITIVE,
        score=51.0,
        confidence=0.79,
        probabilities=SentimentProbabilities(
            positive=0.68,
            neutral=0.2,
            negative=0.12,
        ),
        aggregation_strategy=AggregationStrategy.WEIGHTED_MEAN,
        chunk_results=[],
        disagreement_ratio=0.0,
        chunk_count=0,
    )

    result = explain_sentiment(
        title="",
        article_text="Revenue rose strongly.",
        sentiment_result=sentiment_result,
    )

    assert result.target_label == FinBERTSentimentLabel.POSITIVE


def test_attention_explainer_uses_sentiment_body_chunk_scope_for_longer_articles(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.xai.attention_explainer.score_text_with_attentions",
        lambda text: SimpleNamespace(
            truncated=False,
            token_scores=[
                AttentionTokenScore(
                    token="Downgrade",
                    start_char=0,
                    end_char=9,
                    attention_weight=0.95,
                ),
            ],
        ),
    )
    article_text = (
        "Intro sentence that should not be highlighted. "
        "Downgrade drove shares lower after weak guidance."
    )
    target_chunk = "Downgrade drove shares lower after weak guidance."
    sentiment_result = SentimentResult(
        label=FinBERTSentimentLabel.NEGATIVE,
        score=-58.0,
        confidence=0.82,
        probabilities=SentimentProbabilities(
            positive=0.08,
            neutral=0.18,
            negative=0.74,
        ),
        aggregation_strategy=AggregationStrategy.WEIGHTED_MEAN,
        chunk_results=[
            ChunkSentimentResult(
                chunk_index=0,
                source=SentimentChunkSource.BODY,
                text="Intro sentence that should not be highlighted.",
                token_count=8,
                weight=0.4,
                label=FinBERTSentimentLabel.NEUTRAL,
                score=0.0,
                confidence=0.5,
                probabilities=SentimentProbabilities(
                    positive=0.2,
                    neutral=0.6,
                    negative=0.2,
                ),
            ),
            ChunkSentimentResult(
                chunk_index=1,
                source=SentimentChunkSource.BODY,
                text=target_chunk,
                token_count=8,
                weight=1.0,
                label=FinBERTSentimentLabel.NEGATIVE,
                score=-58.0,
                confidence=0.82,
                probabilities=SentimentProbabilities(
                    positive=0.08,
                    neutral=0.18,
                    negative=0.74,
                ),
            ),
        ],
        disagreement_ratio=0.0,
        chunk_count=2,
    )

    result = explain_sentiment(
        title="",
        article_text=article_text,
        sentiment_result=sentiment_result,
    )

    assert result.highlights
    assert result.highlights[0].text_snippet == target_chunk
    assert result.highlights[0].start_char == article_text.index(target_chunk)


def test_attention_explainer_filters_stopword_and_short_noise_sentences(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.xai.attention_explainer.score_text_with_attentions",
        lambda text: SimpleNamespace(
            truncated=False,
            token_scores=[
                AttentionTokenScore(
                    token="the",
                    start_char=0,
                    end_char=3,
                    attention_weight=0.99,
                ),
                AttentionTokenScore(
                    token="Revenue",
                    start_char=5,
                    end_char=12,
                    attention_weight=0.55,
                ),
                AttentionTokenScore(
                    token="guidance",
                    start_char=13,
                    end_char=21,
                    attention_weight=0.5,
                ),
            ],
        ),
    )
    article_text = "The. Revenue guidance improved."
    sentiment_result = SentimentResult(
        label=FinBERTSentimentLabel.POSITIVE,
        score=48.0,
        confidence=0.77,
        probabilities=SentimentProbabilities(
            positive=0.66,
            neutral=0.22,
            negative=0.12,
        ),
        aggregation_strategy=AggregationStrategy.WEIGHTED_MEAN,
        chunk_results=[],
        disagreement_ratio=0.0,
        chunk_count=0,
    )

    result = explain_sentiment(
        title="",
        article_text=article_text,
        sentiment_result=sentiment_result,
    )

    assert result.highlights
    assert result.highlights[0].text_snippet == "Revenue guidance improved."


def test_attention_explainer_review_case_positive_article_picks_guidance_sentence(
    monkeypatch,
) -> None:
    target_sentence = "Management raised full-year guidance."
    title = "Company raises outlook after quarterly results"
    body_offset = len(title) + 2
    monkeypatch.setattr(
        "app.services.xai.attention_explainer.score_text_with_attentions",
        lambda text: SimpleNamespace(
            truncated=False,
            token_scores=[
                AttentionTokenScore(
                    token="Management",
                    start_char=body_offset,
                    end_char=body_offset + 10,
                    attention_weight=0.72,
                ),
                AttentionTokenScore(
                    token="guidance",
                    start_char=body_offset + 29,
                    end_char=body_offset + 37,
                    attention_weight=0.81,
                ),
            ],
        ),
    )
    article_text = (
        "Revenue rose 12% year over year. "
        "Operating margin improved in the quarter. "
        f"{target_sentence}"
    )
    sentiment_result = SentimentResult(
        label=FinBERTSentimentLabel.POSITIVE,
        score=63.0,
        confidence=0.83,
        probabilities=SentimentProbabilities(
            positive=0.79,
            neutral=0.14,
            negative=0.07,
        ),
        aggregation_strategy=AggregationStrategy.WEIGHTED_MEAN,
        chunk_results=[
            ChunkSentimentResult(
                chunk_index=0,
                source=SentimentChunkSource.BODY,
                text="Revenue rose 12% year over year.",
                token_count=8,
                weight=0.6,
                label=FinBERTSentimentLabel.POSITIVE,
                score=41.0,
                confidence=0.68,
                probabilities=SentimentProbabilities(
                    positive=0.62,
                    neutral=0.25,
                    negative=0.13,
                ),
            ),
            ChunkSentimentResult(
                chunk_index=1,
                source=SentimentChunkSource.BODY,
                text="Operating margin improved in the quarter.",
                token_count=7,
                weight=0.7,
                label=FinBERTSentimentLabel.POSITIVE,
                score=48.0,
                confidence=0.72,
                probabilities=SentimentProbabilities(
                    positive=0.67,
                    neutral=0.22,
                    negative=0.11,
                ),
            ),
            ChunkSentimentResult(
                chunk_index=2,
                source=SentimentChunkSource.BODY,
                text=target_sentence,
                token_count=5,
                weight=1.0,
                label=FinBERTSentimentLabel.POSITIVE,
                score=63.0,
                confidence=0.83,
                probabilities=SentimentProbabilities(
                    positive=0.79,
                    neutral=0.14,
                    negative=0.07,
                ),
            ),
        ],
        disagreement_ratio=0.0,
        chunk_count=3,
    )

    result = explain_sentiment(
        title=title,
        article_text=article_text,
        sentiment_result=sentiment_result,
    )

    assert result.highlights
    assert result.highlights[0].text_snippet == target_sentence


def test_attention_explainer_review_case_mixed_article_prefers_negative_driver(
    monkeypatch,
) -> None:
    target_sentence = "Margins deteriorated because of restructuring charges."
    target_offset = len("Revenue rose ahead of expectations. ")
    monkeypatch.setattr(
        "app.services.xai.attention_explainer.score_text_with_attentions",
        lambda text: SimpleNamespace(
            truncated=False,
            token_scores=[
                AttentionTokenScore(
                    token="Margins",
                    start_char=0,
                    end_char=7,
                    attention_weight=0.76,
                ),
                AttentionTokenScore(
                    token="restructuring",
                    start_char=31,
                    end_char=44,
                    attention_weight=0.88,
                ),
            ],
        ),
    )
    article_text = (
        "Revenue rose ahead of expectations. "
        f"{target_sentence} "
        "Management maintained annual guidance."
    )
    sentiment_result = SentimentResult(
        label=FinBERTSentimentLabel.NEGATIVE,
        score=-22.0,
        confidence=0.54,
        probabilities=SentimentProbabilities(
            positive=0.25,
            neutral=0.21,
            negative=0.54,
        ),
        aggregation_strategy=AggregationStrategy.WEIGHTED_MEAN,
        chunk_results=[
            ChunkSentimentResult(
                chunk_index=0,
                source=SentimentChunkSource.BODY,
                text="Revenue rose ahead of expectations.",
                token_count=6,
                weight=0.6,
                label=FinBERTSentimentLabel.POSITIVE,
                score=28.0,
                confidence=0.61,
                probabilities=SentimentProbabilities(
                    positive=0.58,
                    neutral=0.24,
                    negative=0.18,
                ),
            ),
            ChunkSentimentResult(
                chunk_index=1,
                source=SentimentChunkSource.BODY,
                text=target_sentence,
                token_count=7,
                weight=1.0,
                label=FinBERTSentimentLabel.NEGATIVE,
                score=-47.0,
                confidence=0.74,
                probabilities=SentimentProbabilities(
                    positive=0.12,
                    neutral=0.14,
                    negative=0.74,
                ),
            ),
            ChunkSentimentResult(
                chunk_index=2,
                source=SentimentChunkSource.BODY,
                text="Management maintained annual guidance.",
                token_count=5,
                weight=0.5,
                label=FinBERTSentimentLabel.NEUTRAL,
                score=0.0,
                confidence=0.56,
                probabilities=SentimentProbabilities(
                    positive=0.22,
                    neutral=0.56,
                    negative=0.22,
                ),
            ),
        ],
        disagreement_ratio=0.35,
        chunk_count=3,
    )

    result = explain_sentiment(
        title="Mixed signals after earnings",
        article_text=article_text,
        sentiment_result=sentiment_result,
    )

    assert result.highlights
    assert result.highlights[0].text_snippet == target_sentence
    assert result.highlights[0].start_char == target_offset