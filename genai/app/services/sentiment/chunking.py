from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Callable

from app.schemas.sentiment import (
    AggregationStrategy,
    ChunkSentimentResult,
    FinBERTSentimentLabel,
    SentimentChunkSource,
    SentimentProbabilities,
    SentimentResult,
)


_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+|\n+")
_CLAUSE_SPLIT_PATTERN = re.compile(
    r";|:|, (?=(?:but|while|as|after|before|despite)\b)",
    re.IGNORECASE,
)
_MULTI_SPACE_PATTERN = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class TextChunk:
    index: int
    text: str
    token_count: int
    weight: float
    source: SentimentChunkSource = SentimentChunkSource.BODY


def chunk_article_text(
    text: str,
    *,
    token_count_fn: Callable[[str], int],
    max_tokens: int = 448,
    overlap_sentences: int = 1,
    max_chunks: int = 8,
) -> list[TextChunk]:
    """Split article text into sentence-aware chunks sized for model inference."""
    normalized_text = _normalize_text(text)
    if not normalized_text:
        return []

    sentences = _prepare_sentences(
        text=normalized_text,
        token_count_fn=token_count_fn,
        max_tokens=max_tokens,
    )
    if not sentences:
        return []

    chunks: list[TextChunk] = []
    start_index = 0

    while start_index < len(sentences) and len(chunks) < max_chunks:
        chunk_sentences: list[str] = []
        chunk_tokens = 0
        cursor = start_index

        while cursor < len(sentences):
            sentence = sentences[cursor]
            sentence_tokens = token_count_fn(sentence)
            proposed_tokens = chunk_tokens + sentence_tokens

            if chunk_sentences and proposed_tokens > max_tokens:
                break

            chunk_sentences.append(sentence)
            chunk_tokens = proposed_tokens
            cursor += 1

            if chunk_tokens >= max_tokens:
                break

        if not chunk_sentences:
            break

        chunk_text = " ".join(chunk_sentences).strip()
        chunks.append(
            TextChunk(
                index=len(chunks),
                text=chunk_text,
                token_count=max(1, token_count_fn(chunk_text)),
                weight=_default_chunk_weight(chunk_text=chunk_text, position=len(chunks)),
            )
        )

        if cursor >= len(sentences):
            break

        start_index = max(start_index + 1, cursor - max(0, overlap_sentences))

    return chunks


def build_chunk_sentiment_result(
    *,
    chunk_index: int,
    text: str,
    token_count: int,
    weight: float,
    probabilities: SentimentProbabilities,
    source: SentimentChunkSource = SentimentChunkSource.BODY,
    positive_score_threshold: float = 8.0,
    negative_score_threshold: float = -8.0,
) -> ChunkSentimentResult:
    """Convert raw class probabilities into a chunk-level sentiment result."""
    label = _determine_label(
        probabilities,
        positive_score_threshold=positive_score_threshold,
        negative_score_threshold=negative_score_threshold,
    )
    confidence = round(
        max(probabilities.positive, probabilities.neutral, probabilities.negative),
        4,
    )
    score = round((probabilities.positive - probabilities.negative) * 100, 2)
    return ChunkSentimentResult(
        chunk_index=chunk_index,
        source=source,
        text=text,
        token_count=token_count,
        weight=round(weight, 4),
        label=label,
        score=score,
        confidence=confidence,
        probabilities=probabilities,
    )


def aggregate_chunk_results(
    chunk_results: list[ChunkSentimentResult],
    *,
    strategy: AggregationStrategy = AggregationStrategy.WEIGHTED_MEAN,
    positive_score_threshold: float = 8.0,
    negative_score_threshold: float = -8.0,
) -> SentimentResult:
    """Aggregate chunk-level sentiment into one article-level result."""
    if not chunk_results:
        neutral = SentimentProbabilities(positive=0.0, neutral=1.0, negative=0.0)
        return SentimentResult(
            label=FinBERTSentimentLabel.NEUTRAL,
            score=0.0,
            confidence=1.0,
            probabilities=neutral,
            aggregation_strategy=strategy,
            chunk_results=[],
            disagreement_ratio=0.0,
            chunk_count=0,
        )

    weights = _resolve_weights(chunk_results=chunk_results, strategy=strategy)
    total_weight = sum(weights)
    if math.isclose(total_weight, 0.0):
        weights = [1.0] * len(chunk_results)
        total_weight = float(len(chunk_results))

    positive = sum(
        chunk.probabilities.positive * weight
        for chunk, weight in zip(chunk_results, weights, strict=True)
    ) / total_weight
    neutral = sum(
        chunk.probabilities.neutral * weight
        for chunk, weight in zip(chunk_results, weights, strict=True)
    ) / total_weight
    negative = sum(
        chunk.probabilities.negative * weight
        for chunk, weight in zip(chunk_results, weights, strict=True)
    ) / total_weight

    total_probability = positive + neutral + negative
    probabilities = SentimentProbabilities(
        positive=round(positive / total_probability, 6),
        neutral=round(neutral / total_probability, 6),
        negative=round(negative / total_probability, 6),
    )
    label = _determine_label(
        probabilities,
        positive_score_threshold=positive_score_threshold,
        negative_score_threshold=negative_score_threshold,
    )
    confidence = round(
        max(probabilities.positive, probabilities.neutral, probabilities.negative),
        4,
    )
    disagreement_ratio = round(
        sum(
            weight
            for chunk, weight in zip(chunk_results, weights, strict=True)
            if chunk.label != label
        )
        / total_weight,
        4,
    )

    return SentimentResult(
        label=label,
        score=round((probabilities.positive - probabilities.negative) * 100, 2),
        confidence=confidence,
        probabilities=probabilities,
        aggregation_strategy=strategy,
        chunk_results=chunk_results,
        disagreement_ratio=disagreement_ratio,
        chunk_count=len(chunk_results),
    )


def _prepare_sentences(
    *,
    text: str,
    token_count_fn: Callable[[str], int],
    max_tokens: int,
) -> list[str]:
    sentences: list[str] = []
    for raw_part in _SENTENCE_SPLIT_PATTERN.split(text):
        sentence = _normalize_text(raw_part)
        if not sentence:
            continue
        if token_count_fn(sentence) <= max_tokens:
            sentences.append(sentence)
            continue
        sentences.extend(
            _split_oversized_sentence(
                sentence=sentence,
                token_count_fn=token_count_fn,
                max_tokens=max_tokens,
            )
        )
    return sentences


def _split_oversized_sentence(
    *,
    sentence: str,
    token_count_fn: Callable[[str], int],
    max_tokens: int,
) -> list[str]:
    clauses = [
        normalized
        for part in _CLAUSE_SPLIT_PATTERN.split(sentence)
        if (normalized := _normalize_text(part))
    ]
    if len(clauses) <= 1:
        return _split_sentence_by_words(
            sentence=sentence,
            token_count_fn=token_count_fn,
            max_tokens=max_tokens,
        )

    results: list[str] = []
    current_parts: list[str] = []
    for clause in clauses:
        proposal = " ".join(current_parts + [clause]).strip()
        if current_parts and token_count_fn(proposal) > max_tokens:
            results.append(" ".join(current_parts).strip())
            current_parts = [clause]
        else:
            current_parts.append(clause)

    if current_parts:
        results.append(" ".join(current_parts).strip())

    expanded: list[str] = []
    for item in results:
        if token_count_fn(item) > max_tokens:
            expanded.extend(
                _split_sentence_by_words(
                    sentence=item,
                    token_count_fn=token_count_fn,
                    max_tokens=max_tokens,
                )
            )
        else:
            expanded.append(item)
    return expanded


def _split_sentence_by_words(
    *,
    sentence: str,
    token_count_fn: Callable[[str], int],
    max_tokens: int,
) -> list[str]:
    words = sentence.split()
    if not words:
        return []

    parts: list[str] = []
    current_words: list[str] = []
    for word in words:
        proposal = " ".join(current_words + [word]).strip()
        if current_words and token_count_fn(proposal) > max_tokens:
            parts.append(" ".join(current_words).strip())
            current_words = [word]
        else:
            current_words.append(word)

    if current_words:
        parts.append(" ".join(current_words).strip())
    return parts


def _resolve_weights(
    *,
    chunk_results: list[ChunkSentimentResult],
    strategy: AggregationStrategy,
) -> list[float]:
    if strategy == AggregationStrategy.MEAN:
        return [1.0] * len(chunk_results)
    return [max(chunk.weight, 0.0) for chunk in chunk_results]


def _default_chunk_weight(*, chunk_text: str, position: int) -> float:
    token_count = max(1, len(chunk_text.split()))
    length_factor = min(token_count / 120, 1.0)
    position_penalty = min(position * 0.08, 0.3)
    return max(0.55, length_factor - position_penalty)


def _determine_label(
    probabilities: SentimentProbabilities,
    *,
    positive_score_threshold: float,
    negative_score_threshold: float,
) -> FinBERTSentimentLabel:
    positive_threshold, negative_threshold = _normalize_score_thresholds(
        positive_score_threshold=positive_score_threshold,
        negative_score_threshold=negative_score_threshold,
    )
    score = (probabilities.positive - probabilities.negative) * 100.0
    if score >= positive_threshold:
        return FinBERTSentimentLabel.POSITIVE
    if score <= negative_threshold:
        return FinBERTSentimentLabel.NEGATIVE
    return FinBERTSentimentLabel.NEUTRAL


def _normalize_score_thresholds(
    *,
    positive_score_threshold: float,
    negative_score_threshold: float,
) -> tuple[float, float]:
    positive = max(0.0, float(positive_score_threshold))
    negative = min(0.0, float(negative_score_threshold))
    if positive <= negative:
        return 8.0, -8.0
    return positive, negative


def _normalize_text(text: str) -> str:
    return _MULTI_SPACE_PATTERN.sub(" ", text).strip()