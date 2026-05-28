from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

import numpy as np
from lime.lime_text import LimeTextExplainer

from app.schemas.sentiment import FinBERTSentimentLabel
from app.schemas.xai import (
    XAIContributionDirection,
    XAIHighlight,
    XAIKeywordSpan,
    XAIResult,
)
from app.services.sentiment import analyze_sentiment, predict_text_probabilities
from app.services.text_cleaner import clean_article_text


DEFAULT_MAX_SENTENCES: Final[int] = 12
DEFAULT_NUM_FEATURES: Final[int] = 6
DEFAULT_NUM_SAMPLES: Final[int] = 400
EXPLAINER_RANDOM_STATE: Final[int] = 17
LABEL_ORDER: Final[list[FinBERTSentimentLabel]] = [
    FinBERTSentimentLabel.POSITIVE,
    FinBERTSentimentLabel.NEUTRAL,
    FinBERTSentimentLabel.NEGATIVE,
]

_SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+|\n+")
_MULTI_SPACE_PATTERN = re.compile(r"\s+")
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
MAX_KEYWORD_SPANS_PER_HIGHLIGHT: Final[int] = 3


@dataclass(frozen=True, slots=True)
class SentenceSpan:
    index: int
    text: str
    start_char: int
    end_char: int


def explain_sentiment(title: str, article_text: str) -> XAIResult:
    """Return a sentence-level LIME explanation for the article sentiment result."""
    cleaned_text = clean_article_text(article_text)
    if not cleaned_text:
        return XAIResult(
            target_label=FinBERTSentimentLabel.NEUTRAL,
            highlights=[],
            limitations=[
                "Explanation requires non-empty article text after cleaning.",
            ],
            sentence_count=0,
            truncated=False,
        )

    sentiment_result = analyze_sentiment(title=title, article_text=cleaned_text)
    selected_sentence_spans, truncated = _select_sentence_scope(
        article_text=cleaned_text,
        max_sentences=DEFAULT_MAX_SENTENCES,
    )

    if not selected_sentence_spans:
        return XAIResult(
            target_label=sentiment_result.label,
            highlights=[],
            limitations=[
                "No explainable sentence units were available after preprocessing.",
            ],
            sentence_count=0,
            truncated=False,
        )

    sentence_ids = [f"s{index}" for index in range(len(selected_sentence_spans))]
    sentence_lookup = {
        sentence_id: span
        for sentence_id, span in zip(sentence_ids, selected_sentence_spans, strict=True)
    }
    surrogate_document = " ".join(sentence_ids)

    explainer = LimeTextExplainer(
        class_names=[label.value for label in LABEL_ORDER],
        split_expression=r"\s+",
        bow=True,
        random_state=EXPLAINER_RANDOM_STATE,
    )
    target_label_index = LABEL_ORDER.index(sentiment_result.label)
    explanation = explainer.explain_instance(
        surrogate_document,
        classifier_fn=lambda docs: _predict_surrogate_documents(
            documents=docs,
            sentence_lookup=sentence_lookup,
            title=title,
        ),
        labels=[target_label_index],
        num_features=min(DEFAULT_NUM_FEATURES, len(selected_sentence_spans)),
        num_samples=DEFAULT_NUM_SAMPLES,
    )

    highlights = _build_highlights(
        explanation_items=explanation.as_list(label=target_label_index),
        sentence_lookup=sentence_lookup,
    )
    return XAIResult(
        target_label=sentiment_result.label,
        highlights=highlights,
        limitations=[
            "This MVP explanation is sentence-level, not token- or span-exact.",
            "LIME provides a local approximation of model behavior and is not causal proof.",
            "Long articles may be subsetted to a limited sentence window for stability and speed.",
        ],
        sentence_count=len(selected_sentence_spans),
        truncated=truncated,
    )


def _select_sentence_scope(
    *,
    article_text: str,
    max_sentences: int,
) -> tuple[list[SentenceSpan], bool]:
    sentence_spans = _split_sentence_spans(article_text)
    if len(sentence_spans) <= max_sentences:
        return sentence_spans, False
    return sentence_spans[:max_sentences], True


def _split_sentence_spans(article_text: str) -> list[SentenceSpan]:
    sentence_spans: list[SentenceSpan] = []
    cursor = 0

    for part in _SENTENCE_SPLIT_PATTERN.split(article_text):
        raw_part = part
        if not raw_part:
            cursor += len(raw_part)
            continue

        start_offset = 0
        end_offset = len(raw_part)
        while start_offset < end_offset and raw_part[start_offset].isspace():
            start_offset += 1
        while end_offset > start_offset and raw_part[end_offset - 1].isspace():
            end_offset -= 1

        normalized = _MULTI_SPACE_PATTERN.sub(" ", raw_part[start_offset:end_offset]).strip()
        if normalized:
            sentence_spans.append(
                SentenceSpan(
                    index=len(sentence_spans),
                    text=normalized,
                    start_char=cursor + start_offset,
                    end_char=cursor + end_offset,
                )
            )

        cursor += len(raw_part)
        if cursor < len(article_text):
            while cursor < len(article_text) and article_text[cursor].isspace():
                cursor += 1

    return sentence_spans


def _predict_surrogate_documents(
    *,
    documents: list[str],
    sentence_lookup: dict[str, SentenceSpan],
    title: str,
) -> np.ndarray:
    reconstructed_texts: list[str] = []
    for document in documents:
        selected_ids = [token for token in document.split() if token in sentence_lookup]
        selected_sentences = [sentence_lookup[token].text for token in selected_ids]
        body_text = " ".join(selected_sentences).strip()
        if title.strip() and body_text:
            reconstructed_texts.append(f"{title.strip()}\n\n{body_text}")
        elif body_text:
            reconstructed_texts.append(body_text)
        else:
            reconstructed_texts.append(title.strip() or "neutral")

    probabilities = predict_text_probabilities(reconstructed_texts)
    matrix = [
        [
            item.positive,
            item.neutral,
            item.negative,
        ]
        for item in probabilities
    ]
    return np.array(matrix, dtype=float)


def _build_highlights(
    *,
    explanation_items: list[tuple[str, float]],
    sentence_lookup: dict[str, SentenceSpan],
) -> list[XAIHighlight]:
    highlights: list[XAIHighlight] = []
    for feature_name, weight in explanation_items:
        sentence_span = sentence_lookup.get(feature_name)
        if sentence_span is None:
            continue
        highlights.append(
            XAIHighlight(
                text_snippet=sentence_span.text,
                weight=round(weight, 6),
                importance_score=round(abs(weight), 6),
                contribution_direction=(
                    XAIContributionDirection.POSITIVE
                    if weight >= 0
                    else XAIContributionDirection.NEGATIVE
                ),
                sentence_index=sentence_span.index,
                start_char=sentence_span.start_char,
                end_char=sentence_span.end_char,
                keyword_spans=_extract_keyword_spans(
                    sentence_span=sentence_span,
                    sentence_importance=round(abs(weight), 6),
                ),
            )
        )
    return highlights


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