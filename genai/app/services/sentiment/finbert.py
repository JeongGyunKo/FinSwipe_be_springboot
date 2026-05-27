"""FinBERT 감성 분석 — ProsusAI/finbert 로컬 모델"""
import logging
import threading

from app.services.sentiment.chunking import (
    ArticleSentimentResult,
    ChunkSentimentResult,
    chunk_article_text,
    build_chunk_sentiment_result,
    aggregate_chunk_results,
    position_weight,
)

logger = logging.getLogger(__name__)

MODEL_NAME = "ProsusAI/finbert"
TITLE_WEIGHT_MULTIPLIER = 1.25  # 제목 감성 가중치

_model = None
_tokenizer = None
_lock = threading.Lock()


def _load_model():
    """FinBERT 모델 지연 로딩 (스레드 안전)"""
    global _model, _tokenizer
    if _model is not None:
        return _model, _tokenizer

    with _lock:
        if _model is not None:
            return _model, _tokenizer

        try:
            from transformers import AutoTokenizer, AutoModelForSequenceClassification
            import torch  # noqa: F401

            logger.info("[FinBERT] 모델 로딩 중: %s", MODEL_NAME)
            _tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
            _model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME)
            _model.eval()
            logger.info("[FinBERT] 모델 로딩 완료")
        except Exception as e:
            logger.error("[FinBERT] 모델 로딩 실패: %s", e)
            raise RuntimeError(f"FinBERT 로딩 실패: {e}") from e

    return _model, _tokenizer


def _count_tokens(text: str) -> int:
    """텍스트 토큰 수 계산"""
    _, tokenizer = _load_model()
    return len(tokenizer.encode(text, add_special_tokens=False))


def _score_text(text: str) -> list[float]:
    """단일 텍스트 감성 확률 계산 → [positive, negative, neutral]"""
    import torch
    import torch.nn.functional as F

    model, tokenizer = _load_model()

    inputs = tokenizer(
        text,
        return_tensors="pt",
        truncation=True,
        max_length=512,
        padding=True,
    )
    with torch.no_grad():
        outputs = model(**inputs)
        probs = F.softmax(outputs.logits, dim=-1).squeeze().tolist()

    # ProsusAI/finbert 레이블 순서: positive(0), negative(1), neutral(2)
    if isinstance(probs, float):
        probs = [probs, 0.0, 0.0]
    return probs


def predict_text_probabilities(texts: list[str]) -> list[list[float]]:
    """배치 텍스트 감성 확률 예측"""
    return [_score_text(t) for t in texts]


def analyze_sentiment(title: str, article_text: str) -> ArticleSentimentResult:
    """제목 + 본문 전체 감성 분석

    Returns:
        ArticleSentimentResult (label, score, positive, negative, neutral, ...)
    """
    _load_model()  # 미리 로딩 확인

    chunk_results: list[ChunkSentimentResult] = []

    # 제목 감성 (가중치 높게)
    if title and title.strip():
        try:
            title_probs = _score_text(title.strip())
            chunk_results.append(
                build_chunk_sentiment_result(title_probs, weight=TITLE_WEIGHT_MULTIPLIER)
            )
        except Exception as e:
            logger.warning("[FinBERT] 제목 분석 실패: %s", e)

    # 본문 청킹
    if article_text and article_text.strip():
        try:
            chunks = chunk_article_text(article_text, _count_tokens)
            for idx, chunk in enumerate(chunks):
                if not chunk.strip():
                    continue
                probs = _score_text(chunk)
                w = position_weight(idx, len(chunks))
                chunk_results.append(build_chunk_sentiment_result(probs, weight=w))
        except Exception as e:
            logger.error("[FinBERT] 본문 분석 실패: %s", e)

    if not chunk_results:
        return ArticleSentimentResult("neutral", 0.5, 0.33, 0.33, 0.34, 0.0, 0)

    result = aggregate_chunk_results(chunk_results)
    logger.debug(
        "[FinBERT] %s (score=%.3f, pos=%.3f, neg=%.3f, neu=%.3f, disagree=%.3f, chunks=%d)",
        result.label, result.score, result.positive, result.negative,
        result.neutral, result.disagreement_ratio, result.chunk_count,
    )
    return result


def get_predict_fn():
    """LIME에서 사용할 예측 함수 반환 (텍스트 배열 → 확률 행렬)"""
    import numpy as np

    def predict_fn(texts: list[str]) -> "np.ndarray":
        probs = predict_text_probabilities(texts)
        return np.array(probs)

    return predict_fn
