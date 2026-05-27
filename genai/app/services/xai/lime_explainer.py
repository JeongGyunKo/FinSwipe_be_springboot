"""LIME 기반 XAI — 감성 판단 근거 문장/키워드 추출"""
import re
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

MAX_SENTENCES = 12      # 분석할 최대 문장 수
NUM_FEATURES  = 6       # 추출할 핵심 특성 수
NUM_SAMPLES   = 400     # LIME 샘플 수

# 영문 불용어
STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "shall", "can", "this", "that",
    "these", "those", "it", "its", "they", "them", "their", "we", "our",
    "you", "your", "he", "she", "his", "her", "said", "says", "also",
    "as", "than", "then", "so", "if", "not", "no", "more", "which",
}


@dataclass
class Highlight:
    sentence: str
    weight: float           # 양수=positive 기여, 음수=negative 기여
    direction: str          # "positive" | "negative" | "neutral"
    keywords: list[str] = field(default_factory=list)


@dataclass
class XAIResult:
    highlights: list[Highlight]
    keywords: list[str]     # 전체 상위 키워드


def explain_sentiment(article_text: str, sentiment_label: str,
                      predict_fn) -> XAIResult:
    """LIME으로 감성 판단 근거 추출

    Args:
        article_text: 분석할 기사 본문
        sentiment_label: FinBERT 감성 결과 (positive/negative/neutral/mixed)
        predict_fn: FinBERT predict_fn (텍스트 배열 → 확률 행렬)

    Returns:
        XAIResult (highlights, keywords)
    """
    try:
        from lime.lime_text import LimeTextExplainer
    except ImportError:
        logger.warning("[LIME] lime 패키지 없음 → XAI 스킵")
        return XAIResult(highlights=[], keywords=[])

    sentences = _split_sentences(article_text)
    if not sentences:
        return XAIResult(highlights=[], keywords=[])

    sentences = sentences[:MAX_SENTENCES]
    sentence_map = {f"__s{i}__": s for i, s in enumerate(sentences)}

    # 문장 ID 대리 문서 생성
    surrogate_doc = " ".join(sentence_map.keys())

    # 타겟 감성 클래스 인덱스 (positive=0, negative=1, neutral=2)
    label_to_idx = {"positive": 0, "negative": 1, "neutral": 2, "mixed": 0}
    target_idx = label_to_idx.get(sentiment_label, 0)

    def surrogate_predict(texts: list[str]):
        """대리 문서 → 원본 문장 복원 후 예측"""
        reconstructed = []
        for t in texts:
            ids = re.findall(r"__s\d+__", t)
            orig = " ".join(sentence_map[sid] for sid in ids if sid in sentence_map)
            reconstructed.append(orig if orig else ".")
        return predict_fn(reconstructed)

    try:
        explainer = LimeTextExplainer(
            class_names=["positive", "negative", "neutral"],
            split_expression=r"\s+",
            bow=True,
        )
        explanation = explainer.explain_instance(
            surrogate_doc,
            surrogate_predict,
            num_features=NUM_FEATURES,
            num_samples=NUM_SAMPLES,
            labels=[target_idx],
        )
        feature_weights = dict(explanation.as_list(label=target_idx))
    except Exception as e:
        logger.error("[LIME] 설명 생성 실패: %s", e)
        return XAIResult(highlights=[], keywords=[])

    # 가중치 높은 문장 식별
    highlights: list[Highlight] = []
    for sid, sentence in sentence_map.items():
        w = feature_weights.get(sid, 0.0)
        if abs(w) < 0.01:
            continue
        direction = "positive" if w > 0 else "negative"
        kws = _extract_keywords(sentence, top_n=4)
        highlights.append(Highlight(sentence=sentence, weight=round(w, 4),
                                    direction=direction, keywords=kws))

    highlights.sort(key=lambda h: abs(h.weight), reverse=True)

    # 전체 상위 키워드
    all_keywords = _extract_keywords(
        " ".join(s for s in sentences), top_n=NUM_FEATURES
    )

    return XAIResult(highlights=highlights[:NUM_FEATURES], keywords=all_keywords)


def xai_result_to_dict(result: XAIResult) -> dict:
    """XAI 결과를 JSON 직렬화 가능한 dict로 변환"""
    return {
        "keywords": result.keywords,
        "highlights": [
            {
                "sentence": h.sentence,
                "weight": h.weight,
                "direction": h.direction,
                "keywords": h.keywords,
            }
            for h in result.highlights
        ],
    }


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _extract_keywords(text: str, top_n: int = 6) -> list[str]:
    """단어 빈도 + 금융 점수 기반 키워드 추출"""
    words = re.findall(r"\b[a-zA-Z$%\d]+\b", text)
    scored: dict[str, float] = {}
    for w in words:
        lower = w.lower()
        if lower in STOPWORDS or len(lower) < 3:
            continue
        score = scored.get(lower, 0.0) + 1.0
        # 숫자/퍼센트/달러 포함 시 가중치
        if re.search(r"[\d$%]", w):
            score += 1.5
        scored[lower] = score

    top = sorted(scored.items(), key=lambda x: x[1], reverse=True)[:top_n]
    return [w for w, _ in top]
