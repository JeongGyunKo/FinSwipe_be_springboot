from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from app.schemas.sentiment import (
    ChunkSentimentResult,
    FinBERTSentimentLabel,
    SentimentChunkSource,
    SentimentResult,
)
from app.schemas.xai import (
    XAIContributionDirection,
    XAIHighlight,
    XAIKeywordSpan,
    XAIResult,
)
from app.services.sentiment import analyze_sentiment, score_text_with_attentions
from app.services.text_cleaner import clean_article_text


DEFAULT_MAX_SENTENCES: Final[int] = 12
DEFAULT_MAX_HIGHLIGHTS: Final[int] = 5
MAX_KEYWORD_SPANS_PER_HIGHLIGHT: Final[int] = 3
MIN_HIGHLIGHT_SENTENCE_LENGTH: Final[int] = 12
MIN_INFORMATIVE_TOKEN_COUNT: Final[int] = 2
_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+|\n+")
_MULTI_SPACE_PATTERN = re.compile(r"\s+")
_ALPHANUMERIC_PATTERN = re.compile(r"[A-Za-z0-9]")
_TOKEN_PATTERN = re.compile(r"\b(?:[A-Za-z]{3,}|[A-Za-z]+\d+|\d+(?:\.\d+)?%?)\b")
_STOPWORDS: Final[set[str]] = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "were",
    "have",
    "has",
    "had",
    "will",
    "into",
    "after",
    "before",
    "their",
    "they",
    "about",
    "while",
    "where",
    "which",
    "because",
    "could",
    "would",
    "should",
    "than",
    "them",
    "been",
    "being",
}


@dataclass(frozen=True, slots=True)
class SentenceSpan:
    index: int
    text: str
    start_char: int
    end_char: int


@dataclass(frozen=True, slots=True)
class SentenceAttentionScore:
    span: SentenceSpan
    raw_score: float
    token_count: int


@dataclass(frozen=True, slots=True)
class ScopeSelection:
    text: str
    start_char: int
    truncated: bool


@dataclass(frozen=True, slots=True)
class LocatedBodyChunk:
    chunk: ChunkSentimentResult
    start_char: int
    end_char: int


def explain_sentiment(
    title: str,
    article_text: str,
    *,
    sentiment_result: SentimentResult | None = None,
) -> XAIResult:
    """Return a sentence-level attention-based explanation for the article sentiment."""
    cleaned_text = clean_article_text(article_text)
    if not cleaned_text:
        return XAIResult(
            target_label=FinBERTSentimentLabel.NEUTRAL,
            explanation_method="attention_sentence",
            highlights=[],
            limitations=[
                "Explanation requires non-empty article text after cleaning.",
            ],
            sentence_count=0,
            truncated=False,
        )

    resolved_sentiment_result = sentiment_result or analyze_sentiment(
        title=title,
        article_text=cleaned_text,
    )
    scope_selection = _resolve_explanation_scope(
        article_text=cleaned_text,
        sentiment_result=resolved_sentiment_result,
    )
    selected_sentence_spans, truncated_scope = _select_sentence_scope(
        article_text=scope_selection.text,
        max_sentences=DEFAULT_MAX_SENTENCES,
        start_offset=scope_selection.start_char,
    )
    if not selected_sentence_spans:
        return XAIResult(
            target_label=resolved_sentiment_result.label,
            explanation_method="attention_sentence",
            highlights=[],
            limitations=[
                "No explainable sentence units were available after preprocessing.",
            ],
            sentence_count=0,
            truncated=False,
        )

    body_scope_relative_end = (
        selected_sentence_spans[-1].end_char - scope_selection.start_char
    )
    body_scope_text = scope_selection.text[:body_scope_relative_end]
    attention_input = _compose_attention_text(title=title, article_text=body_scope_text)
    body_start_offset = _body_start_offset(title=title, article_text=body_scope_text)
    attention_result = score_text_with_attentions(attention_input)

    sentence_scores = _build_sentence_scores(
        sentence_spans=selected_sentence_spans,
        token_scores=attention_result.token_scores,
        body_start_offset=body_start_offset,
        body_scope_start_offset=scope_selection.start_char,
    )
    highlights = _build_highlights(
        sentence_scores=sentence_scores,
        max_highlights=DEFAULT_MAX_HIGHLIGHTS,
    )

    limitations = [
        "This explanation uses last-layer CLS attention aggregated to sentence level.",
        "Attention salience is a heuristic signal and not causal proof of model reasoning.",
        "Long articles may be subsetted to a limited sentence window for stability and speed.",
    ]
    if not highlights:
        limitations.append(
            "No stable sentence highlights were available after attention filtering."
        )

    return XAIResult(
        target_label=resolved_sentiment_result.label,
        explanation_method="attention_sentence",
        highlights=highlights,
        limitations=limitations,
        sentence_count=len(selected_sentence_spans),
        truncated=scope_selection.truncated or truncated_scope or attention_result.truncated,
    )


def _compose_attention_text(*, title: str, article_text: str) -> str:
    title_text = title.strip()
    if title_text and article_text:
        return f"{title_text}\n\n{article_text}"
    return article_text or title_text


def _body_start_offset(*, title: str, article_text: str) -> int:
    title_text = title.strip()
    if title_text and article_text:
        return len(title_text) + 2
    return 0


def _select_sentence_scope(
    *,
    article_text: str,
    max_sentences: int,
    start_offset: int = 0,
) -> tuple[list[SentenceSpan], bool]:
    sentence_spans = _split_sentence_spans(article_text, start_offset=start_offset)
    if len(sentence_spans) <= max_sentences:
        return sentence_spans, False
    return sentence_spans[:max_sentences], True


def _split_sentence_spans(article_text: str, *, start_offset: int = 0) -> list[SentenceSpan]:
    sentence_spans: list[SentenceSpan] = []
    cursor = 0

    for part in _SENTENCE_SPLIT_PATTERN.split(article_text):
        raw_part = part
        if not raw_part:
            cursor += len(raw_part)
            continue

        local_start_offset = 0
        end_offset = len(raw_part)
        while local_start_offset < end_offset and raw_part[local_start_offset].isspace():
            local_start_offset += 1
        while end_offset > local_start_offset and raw_part[end_offset - 1].isspace():
            end_offset -= 1

        normalized = _MULTI_SPACE_PATTERN.sub(
            " ",
            raw_part[local_start_offset:end_offset],
        ).strip()
        if normalized:
            sentence_spans.append(
                SentenceSpan(
                    index=len(sentence_spans),
                    text=normalized,
                    start_char=start_offset + cursor + local_start_offset,
                    end_char=start_offset + cursor + end_offset,
                )
            )

        cursor += len(raw_part)
        if cursor < len(article_text):
            while cursor < len(article_text) and article_text[cursor].isspace():
                cursor += 1

    return sentence_spans


def _build_sentence_scores(
    *,
    sentence_spans: list[SentenceSpan],
    token_scores: list,
    body_start_offset: int,
    body_scope_start_offset: int,
) -> list[SentenceAttentionScore]:
    score_totals = [0.0] * len(sentence_spans)
    token_counts = [0] * len(sentence_spans)

    for token_score in token_scores:
        start_char = getattr(token_score, "start_char", None)
        end_char = getattr(token_score, "end_char", None)
        if start_char is None or end_char is None:
            continue
        if end_char <= body_start_offset:
            continue

        relative_start = max(0, start_char - body_start_offset)
        relative_end = end_char - body_start_offset
        if relative_end <= relative_start:
            continue
        global_start = body_scope_start_offset + relative_start
        global_end = body_scope_start_offset + relative_end

        normalized_token = _normalize_token(getattr(token_score, "token", ""))
        if not _is_useful_token(normalized_token):
            continue

        midpoint = (global_start + global_end) / 2
        sentence_index = _find_sentence_index(sentence_spans=sentence_spans, midpoint=midpoint)
        if sentence_index is None:
            continue

        score_totals[sentence_index] += float(getattr(token_score, "attention_weight", 0.0))
        token_counts[sentence_index] += 1

    sentence_scores: list[SentenceAttentionScore] = []
    for index, span in enumerate(sentence_spans):
        if token_counts[index] == 0:
            continue
        sentence_scores.append(
            SentenceAttentionScore(
                span=span,
                raw_score=score_totals[index] / token_counts[index],
                token_count=token_counts[index],
            )
        )

    return sentence_scores


def _find_sentence_index(
    *,
    sentence_spans: list[SentenceSpan],
    midpoint: float,
) -> int | None:
    for span in sentence_spans:
        if span.start_char <= midpoint < span.end_char:
            return span.index
    return None


def _resolve_explanation_scope(
    *,
    article_text: str,
    sentiment_result: SentimentResult,
) -> ScopeSelection:
    located_body_chunks = _locate_body_chunks(
        article_text=article_text,
        sentiment_result=sentiment_result,
    )
    if not located_body_chunks:
        return ScopeSelection(
            text=article_text,
            start_char=0,
            truncated=False,
        )

    target_label = sentiment_result.label
    selected_chunk = max(
        located_body_chunks,
        key=lambda item: (
            _target_support_score(item.chunk, target_label),
            -item.chunk.chunk_index,
        ),
    )
    return ScopeSelection(
        text=article_text[selected_chunk.start_char:selected_chunk.end_char],
        start_char=selected_chunk.start_char,
        truncated=selected_chunk.start_char > 0 or selected_chunk.end_char < len(article_text),
    )


def _locate_body_chunks(
    *,
    article_text: str,
    sentiment_result: SentimentResult,
) -> list[LocatedBodyChunk]:
    body_chunks = [
        chunk
        for chunk in sentiment_result.chunk_results
        if chunk.source == SentimentChunkSource.BODY and chunk.text.strip()
    ]
    if not body_chunks:
        return []

    located_chunks: list[LocatedBodyChunk] = []
    search_start = 0
    for chunk in body_chunks:
        start_char = article_text.find(chunk.text, search_start)
        if start_char < 0:
            start_char = article_text.find(chunk.text)
        if start_char < 0:
            continue
        end_char = start_char + len(chunk.text)
        located_chunks.append(
            LocatedBodyChunk(
                chunk=chunk,
                start_char=start_char,
                end_char=end_char,
            )
        )
        search_start = max(search_start, start_char + 1)

    return located_chunks


def _target_support_score(
    chunk: ChunkSentimentResult,
    target_label: FinBERTSentimentLabel,
) -> float:
    if target_label == FinBERTSentimentLabel.POSITIVE:
        target_probability = chunk.probabilities.positive
    elif target_label == FinBERTSentimentLabel.NEGATIVE:
        target_probability = chunk.probabilities.negative
    else:
        target_probability = chunk.probabilities.neutral
    return chunk.weight * target_probability


def _build_highlights(
    *,
    sentence_scores: list[SentenceAttentionScore],
    max_highlights: int,
) -> list[XAIHighlight]:
    if not sentence_scores:
        return []

    ranked_scores = sorted(
        (
            item
            for item in sentence_scores
            if _is_informative_sentence(
                sentence_text=item.span.text,
                token_count=item.token_count,
            )
        ),
        key=lambda item: (-item.raw_score, -item.token_count, item.span.index),
    )[:max_highlights]
    if not ranked_scores:
        return []

    max_score = max(item.raw_score for item in ranked_scores) or 1.0

    highlights: list[XAIHighlight] = []
    for item in ranked_scores:
        normalized_score = round(item.raw_score / max_score, 6)
        keyword_spans = _extract_keyword_spans(
            sentence_span=item.span,
            sentence_importance=normalized_score,
        )
        if not keyword_spans and item.token_count < MIN_INFORMATIVE_TOKEN_COUNT:
            continue
        highlights.append(
            XAIHighlight(
                text_snippet=item.span.text,
                weight=normalized_score,
                importance_score=normalized_score,
                contribution_direction=XAIContributionDirection.POSITIVE,
                sentence_index=item.span.index,
                start_char=item.span.start_char,
                end_char=item.span.end_char,
                keyword_spans=keyword_spans,
            )
        )

    return highlights


def _normalize_token(token: str) -> str:
    return token.replace("##", "").strip()


def _is_useful_token(token: str) -> bool:
    if not token:
        return False
    normalized = token.lower()
    if normalized in _STOPWORDS:
        return False
    return bool(_ALPHANUMERIC_PATTERN.search(token))


def _is_informative_sentence(*, sentence_text: str, token_count: int) -> bool:
    stripped = sentence_text.strip()
    if len(stripped) < MIN_HIGHLIGHT_SENTENCE_LENGTH:
        return False
    if token_count >= MIN_INFORMATIVE_TOKEN_COUNT:
        return True

    informative_tokens = [
        match.group(0)
        for match in _TOKEN_PATTERN.finditer(stripped)
        if _is_useful_token(match.group(0))
    ]
    if len(informative_tokens) >= MIN_INFORMATIVE_TOKEN_COUNT:
        return True
    return any(any(character.isdigit() for character in token) for token in informative_tokens)


def _extract_keyword_spans(
    *,
    sentence_span: SentenceSpan,
    sentence_importance: float,
    max_keywords: int = MAX_KEYWORD_SPANS_PER_HIGHLIGHT,
) -> list[XAIKeywordSpan]:
    candidates: list[tuple[float, int, int, str]] = []
    text = sentence_span.text

    for match in _TOKEN_PATTERN.finditer(text):
        token = match.group(0)
        normalized = token.lower()
        if normalized in _STOPWORDS:
            continue

        local_start = match.start()
        local_end = match.end()
        token_score = _score_keyword_candidate(token)
        candidates.append((token_score, local_start, local_end, token))

    candidates.sort(key=lambda item: (-item[0], item[1], item[3].lower()))
    selected = candidates[:max_keywords]

    keyword_spans: list[XAIKeywordSpan] = []
    for token_score, local_start, local_end, token in selected:
        importance = round(min(1.0, max(0.01, sentence_importance * token_score)), 6)
        keyword_spans.append(
            XAIKeywordSpan(
                text_snippet=token,
                start_char=sentence_span.start_char + local_start,
                end_char=sentence_span.start_char + local_end,
                importance_score=importance,
            )
        )

    keyword_spans.sort(key=lambda item: item.start_char)
    return keyword_spans


def _score_keyword_candidate(token: str) -> float:
    score = min(len(token) / 10, 1.0)
    if any(character.isdigit() for character in token):
        score += 0.15
    if "%" in token or "$" in token:
        score += 0.1
    return round(min(score, 1.0), 6)