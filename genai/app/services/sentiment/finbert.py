from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import Final

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from app.core import get_settings
from app.schemas.sentiment import (
    AggregationStrategy,
    FinBERTSentimentLabel,
    SentimentChunkSource,
    SentimentProbabilities,
    SentimentResult,
)
from app.services.sentiment.chunking import (
    aggregate_chunk_results,
    build_chunk_sentiment_result,
    chunk_article_text,
)
from app.services.text_cleaner import clean_article_text


MODEL_NAME: Final[str] = "ProsusAI/finbert"
MODEL_REVISION: Final[str] = os.getenv(
    "GENAI_FINBERT_MODEL_REVISION",
    "4556d13015211d73dccd3fdd39d39232506f3e43",
)
MAX_TOKENS_PER_CHUNK: Final[int] = 448
OVERLAP_SENTENCES: Final[int] = 1
DEFAULT_MAX_CHUNKS: Final[int] = 8
TITLE_WEIGHT: Final[float] = 1.25

_MODEL_LOCK = threading.Lock()
_TOKENIZER = None
_MODEL = None


@dataclass(frozen=True, slots=True)
class AttentionTokenScore:
    token: str
    start_char: int | None
    end_char: int | None
    attention_weight: float


@dataclass(frozen=True, slots=True)
class AttentionScoreResult:
    probabilities: SentimentProbabilities
    token_scores: list[AttentionTokenScore]
    truncated: bool


def analyze_sentiment(
    title: str,
    article_text: str,
    *,
    max_chunk_tokens: int = MAX_TOKENS_PER_CHUNK,
    aggregation_strategy: AggregationStrategy = AggregationStrategy.WEIGHTED_MEAN,
) -> SentimentResult:
    """Run FinBERT sentiment analysis on title-aware article text."""
    settings = get_settings()
    cleaned_text = clean_article_text(article_text)
    if not cleaned_text:
        return SentimentResult(
            label=FinBERTSentimentLabel.NEUTRAL,
            score=0.0,
            confidence=1.0,
            probabilities=SentimentProbabilities(
                positive=0.0,
                neutral=1.0,
                negative=0.0,
            ),
            aggregation_strategy=aggregation_strategy,
            chunk_results=[],
            disagreement_ratio=0.0,
            chunk_count=0,
        )

    tokenizer, model = _get_finbert_components()
    chunk_results = _predict_chunks(
        title=title,
        article_text=cleaned_text,
        tokenizer=tokenizer,
        model=model,
        max_chunk_tokens=max_chunk_tokens,
        positive_score_threshold=settings.sentiment_positive_score_threshold,
        negative_score_threshold=settings.sentiment_negative_score_threshold,
    )
    return aggregate_chunk_results(
        chunk_results,
        strategy=aggregation_strategy,
        positive_score_threshold=settings.sentiment_positive_score_threshold,
        negative_score_threshold=settings.sentiment_negative_score_threshold,
    )


def predict_text_probabilities(texts: list[str]) -> list[SentimentProbabilities]:
    """Return FinBERT class probabilities for a batch of text inputs."""
    if not texts:
        return []

    tokenizer, model = _get_finbert_components()
    return [
        _score_text(
            text=text,
            tokenizer=tokenizer,
            model=model,
        )
        for text in texts
    ]


def score_text_with_attentions(text: str) -> AttentionScoreResult:
    """Return FinBERT probabilities and last-layer CLS-to-token attention weights."""
    stripped = text.strip()
    if not stripped:
        return AttentionScoreResult(
            probabilities=SentimentProbabilities(
                positive=0.0,
                neutral=1.0,
                negative=0.0,
            ),
            token_scores=[],
            truncated=False,
        )

    tokenizer, model = _get_finbert_components()
    encoded = tokenizer(
        stripped,
        truncation=True,
        max_length=512,
        return_tensors="pt",
        return_offsets_mapping=True,
    )
    offset_mapping = encoded.pop("offset_mapping")[0].tolist()
    input_ids = encoded["input_ids"][0].tolist()
    tokens = tokenizer.convert_ids_to_tokens(input_ids)
    sequence_length = len(tokens)
    truncated = bool(sequence_length >= 512)

    with torch.no_grad():
        outputs = model(**encoded, output_attentions=True)
        logits = outputs.logits[0]
        probabilities = torch.softmax(logits, dim=0).tolist()

    attentions = outputs.attentions
    if not attentions:
        raise RuntimeError("FinBERT attention outputs were unavailable.")

    last_layer = attentions[-1][0]
    cls_attention = last_layer[:, 0, :].mean(dim=0).tolist()
    token_scores = [
        AttentionTokenScore(
            token=token,
            start_char=(offset[0] if offset[1] > offset[0] else None),
            end_char=(offset[1] if offset[1] > offset[0] else None),
            attention_weight=float(weight),
        )
        for token, offset, weight in zip(tokens, offset_mapping, cls_attention, strict=True)
    ]

    return AttentionScoreResult(
        probabilities=SentimentProbabilities(
            positive=float(probabilities[0]),
            negative=float(probabilities[1]),
            neutral=float(probabilities[2]),
        ),
        token_scores=token_scores,
        truncated=truncated,
    )


def _get_finbert_components():
    global _TOKENIZER, _MODEL
    if _TOKENIZER is not None and _MODEL is not None:
        return _TOKENIZER, _MODEL

    with _MODEL_LOCK:
        if _TOKENIZER is None:
            # use_fast=False: Python 토크나이저 → GIL로 스레드 안전, 병렬 추론 가능
            # use_fast=True(Rust)는 RefCell로 동시 호출 시 "Already borrowed" 패닉 발생
            _TOKENIZER = AutoTokenizer.from_pretrained(
                MODEL_NAME,
                revision=MODEL_REVISION,
                use_fast=False,
            )
        if _MODEL is None:
            _MODEL = AutoModelForSequenceClassification.from_pretrained(
                MODEL_NAME,
                revision=MODEL_REVISION,
            )
            _MODEL.eval()
        return _TOKENIZER, _MODEL


def _predict_chunks(
    title: str,
    article_text: str,
    tokenizer,
    model,
    *,
    max_chunk_tokens: int,
    positive_score_threshold: float,
    negative_score_threshold: float,
) -> list:
    title_text = title.strip()
    body_chunks = chunk_article_text(
        article_text,
        token_count_fn=lambda text: _count_tokens(text=text, tokenizer=tokenizer),
        max_tokens=max_chunk_tokens,
        overlap_sentences=OVERLAP_SENTENCES,
        max_chunks=DEFAULT_MAX_CHUNKS,
    )
    chunk_results = []

    if title_text:
        title_probabilities = _score_text(
            text=title_text,
            tokenizer=tokenizer,
            model=model,
        )
        chunk_results.append(
            build_chunk_sentiment_result(
                chunk_index=0,
                source=SentimentChunkSource.TITLE,
                text=title_text,
                token_count=_count_tokens(text=title_text, tokenizer=tokenizer),
                weight=TITLE_WEIGHT,
                probabilities=title_probabilities,
                positive_score_threshold=positive_score_threshold,
                negative_score_threshold=negative_score_threshold,
            )
        )

    start_index = len(chunk_results)
    for offset, chunk in enumerate(body_chunks):
        probabilities = _score_text(
            text=chunk.text,
            tokenizer=tokenizer,
            model=model,
        )
        chunk_results.append(
            build_chunk_sentiment_result(
                chunk_index=start_index + offset,
                source=chunk.source,
                text=chunk.text,
                token_count=chunk.token_count,
                weight=chunk.weight,
                probabilities=probabilities,
                positive_score_threshold=positive_score_threshold,
                negative_score_threshold=negative_score_threshold,
            )
        )

    return chunk_results


def _score_text(text: str, tokenizer, model) -> SentimentProbabilities:
    encoded = tokenizer(
        text,
        truncation=True,
        max_length=512,
        return_tensors="pt",
    )

    with torch.no_grad():
        logits = model(**encoded).logits[0]
        probabilities = torch.softmax(logits, dim=0).tolist()

    # FinBERT label order for ProsusAI/finbert is positive, negative, neutral.
    return SentimentProbabilities(
        positive=float(probabilities[0]),
        negative=float(probabilities[1]),
        neutral=float(probabilities[2]),
    )


def _count_tokens(text: str, tokenizer) -> int:
    encoded = tokenizer(
        text,
        add_special_tokens=False,
        return_attention_mask=False,
        return_token_type_ids=False,
    )
    return len(encoded["input_ids"])