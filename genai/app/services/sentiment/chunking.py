"""기사 텍스트 청킹 — FinBERT 512토큰 제한 대응"""
import re
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

MAX_CHUNK_TOKENS = 448   # 512 - special tokens 여유분
SENTENCE_OVERLAP  = 1    # 청크 간 겹치는 문장 수


@dataclass
class ChunkSentimentResult:
    label: str          # positive | negative | neutral
    positive: float
    negative: float
    neutral: float
    weight: float       # 청크 중요도 가중치


@dataclass
class ArticleSentimentResult:
    label: str                        # positive | negative | neutral | mixed
    score: float                      # 최강 감성 확률 (0~1)
    positive: float
    negative: float
    neutral: float
    disagreement_ratio: float         # 청크 간 불일치 비율
    chunk_count: int


def chunk_article_text(text: str, count_tokens_fn, max_tokens: int = MAX_CHUNK_TOKENS) -> list[str]:
    """기사 텍스트를 토큰 제한에 맞게 청크 분할"""
    text = _normalize(text)
    sentences = _split_sentences(text)
    if not sentences:
        return [text[:2000]] if text else []

    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0

    for sent in sentences:
        sent_tokens = count_tokens_fn(sent)
        if sent_tokens > max_tokens:
            # 단일 문장이 너무 길면 단어 단위로 자름
            words = sent.split()
            sub: list[str] = []
            sub_tokens = 0
            for word in words:
                wt = count_tokens_fn(word)
                if sub_tokens + wt > max_tokens and sub:
                    chunks.append(" ".join(sub))
                    sub = sub[-SENTENCE_OVERLAP:] if SENTENCE_OVERLAP else []
                    sub_tokens = count_tokens_fn(" ".join(sub))
                sub.append(word)
                sub_tokens += wt
            if sub:
                current.extend(sub)
                current_tokens += sub_tokens
        elif current_tokens + sent_tokens > max_tokens and current:
            chunks.append(" ".join(current))
            # 오버랩: 마지막 N개 문장 유지
            current = current[-SENTENCE_OVERLAP:] if SENTENCE_OVERLAP else []
            current_tokens = count_tokens_fn(" ".join(current))
            current.append(sent)
            current_tokens += sent_tokens
        else:
            current.append(sent)
            current_tokens += sent_tokens

    if current:
        chunks.append(" ".join(current))

    return chunks or [text[:2000]]


def build_chunk_sentiment_result(probs: list[float], weight: float) -> ChunkSentimentResult:
    """모델 확률 배열 → ChunkSentimentResult
    probs 순서: [positive, negative, neutral] (ProsusAI/finbert 기준)
    """
    positive, negative, neutral = probs[0], probs[1], probs[2]
    idx = probs.index(max(probs))
    label = ["positive", "negative", "neutral"][idx]
    return ChunkSentimentResult(
        label=label,
        positive=positive,
        negative=negative,
        neutral=neutral,
        weight=weight,
    )


def aggregate_chunk_results(chunks: list[ChunkSentimentResult],
                             mixed_threshold: float = 0.35) -> ArticleSentimentResult:
    """청크별 결과 → 기사 레벨 감성 집계"""
    if not chunks:
        return ArticleSentimentResult("neutral", 0.5, 0.33, 0.33, 0.34, 0.0, 0)

    total_weight = sum(c.weight for c in chunks)
    if total_weight == 0:
        total_weight = len(chunks)

    pos = sum(c.positive * c.weight for c in chunks) / total_weight
    neg = sum(c.negative * c.weight for c in chunks) / total_weight
    neu = sum(c.neutral  * c.weight for c in chunks) / total_weight

    # 불일치 비율: 최다 레이블과 다른 청크의 비율
    labels = [c.label for c in chunks]
    dominant = max(set(labels), key=labels.count)
    disagreement = sum(1 for l in labels if l != dominant) / len(labels)

    # mixed 판정: 불일치 비율이 높거나 pos/neg 차이가 작을 때
    if disagreement >= mixed_threshold or (pos > 0.15 and neg > 0.15 and abs(pos - neg) < 0.1):
        label = "mixed"
        score = max(pos, neg)
    else:
        scores = {"positive": pos, "negative": neg, "neutral": neu}
        label = max(scores, key=scores.get)
        score = scores[label]

    return ArticleSentimentResult(
        label=label, score=round(score, 4),
        positive=round(pos, 4), negative=round(neg, 4), neutral=round(neu, 4),
        disagreement_ratio=round(disagreement, 4),
        chunk_count=len(chunks),
    )


def _normalize(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _split_sentences(text: str) -> list[str]:
    """문장 분리 — 마침표/느낌표/물음표 기준"""
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def position_weight(idx: int, total: int) -> float:
    """앞쪽 청크에 더 높은 가중치 (후반부로 갈수록 낮아짐)"""
    if total <= 1:
        return 1.0
    return 1.0 - 0.3 * (idx / (total - 1))
