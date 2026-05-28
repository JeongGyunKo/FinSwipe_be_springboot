from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from math import sqrt

from app.schemas.mixed import (
    ArticleMixedConfig,
    ArticleMixedDetectionResult,
    ArticleMixedReasonCode,
    MixedReason,
    MixedStatus,
    TickerMixedConfig,
    TickerMixedDetectionResult,
    TickerMixedReasonCode,
    TickerSentimentDistribution,
    TickerSentimentObservation,
    compute_lookback_start,
)
from app.schemas.sentiment import FinBERTSentimentLabel, SentimentResult


def detect_article_level_mixed(
    sentiment_result: SentimentResult,
    *,
    config: ArticleMixedConfig | None = None,
) -> ArticleMixedDetectionResult:
    """Detect mixed/conflicting sentiment within a single article.

    Rules:
    - low confidence: final confidence below configured threshold
    - small score gap: absolute article score below configured threshold
    - chunk disagreement: weighted disagreement ratio above configured threshold

    The article is marked mixed when at least `min_trigger_count` rules fire.
    """
    thresholds = config or ArticleMixedConfig()
    triggered_codes: list[ArticleMixedReasonCode] = []

    low_confidence = sentiment_result.confidence < thresholds.confidence_threshold
    reasons = [
        _build_reason(
            code=ArticleMixedReasonCode.LOW_CONFIDENCE,
            triggered=low_confidence,
            value=sentiment_result.confidence,
            threshold=thresholds.confidence_threshold,
            message=(
                "Classifier confidence is below the article-level mixed threshold."
                if low_confidence
                else "Classifier confidence is above the article-level mixed threshold."
            ),
        )
    ]
    if low_confidence:
        triggered_codes.append(ArticleMixedReasonCode.LOW_CONFIDENCE)

    small_score_gap = abs(sentiment_result.score) < thresholds.absolute_score_threshold
    reasons.append(
        _build_reason(
            code=ArticleMixedReasonCode.SMALL_SCORE_GAP,
            triggered=small_score_gap,
            value=abs(sentiment_result.score),
            threshold=thresholds.absolute_score_threshold,
            message=(
                "Positive and negative article-level signals are close in magnitude."
                if small_score_gap
                else "Article-level score shows a clearer directional gap."
            ),
        )
    )
    if small_score_gap:
        triggered_codes.append(ArticleMixedReasonCode.SMALL_SCORE_GAP)

    disagreement = sentiment_result.disagreement_ratio
    chunk_disagreement = disagreement >= thresholds.disagreement_ratio_threshold
    reasons.append(
        _build_reason(
            code=ArticleMixedReasonCode.CHUNK_DISAGREEMENT,
            triggered=chunk_disagreement,
            value=disagreement,
            threshold=thresholds.disagreement_ratio_threshold,
            message=(
                "Chunk-level sentiment signals disagree at a meaningful rate."
                if chunk_disagreement
                else "Chunk-level sentiment signals are mostly consistent."
            ),
        )
    )
    if chunk_disagreement:
        triggered_codes.append(ArticleMixedReasonCode.CHUNK_DISAGREEMENT)

    is_mixed = len(triggered_codes) >= thresholds.min_trigger_count
    return ArticleMixedDetectionResult(
        status=MixedStatus.MIXED if is_mixed else MixedStatus.CLEAR,
        is_mixed=is_mixed,
        has_conflicting_signals=chunk_disagreement,
        dominant_sentiment=None if is_mixed else sentiment_result.label,
        score=sentiment_result.score,
        confidence=sentiment_result.confidence,
        disagreement_ratio=disagreement,
        triggered_reason_codes=triggered_codes,
        reasons=reasons,
        thresholds=thresholds,
    )


def detect_ticker_level_mixed(
    ticker: str,
    recent_articles: list[TickerSentimentObservation],
    *,
    config: TickerMixedConfig | None = None,
    reference_time: datetime | None = None,
) -> TickerMixedDetectionResult:
    """Detect mixed/conflicting sentiment across recent ticker articles.

    Rules:
    - high score variance: recent article scores have high standard deviation
    - conflicting distribution: both positive and negative article ratios exceed
      the configured minimum share inside the recent lookback window

    Articles are filtered to the configured recent window before evaluation.
    If too few recent articles remain, the result is `insufficient_data`.
    """
    thresholds = config or TickerMixedConfig()
    now = (reference_time or datetime.now(timezone.utc)).astimezone(timezone.utc)
    lookback_start = compute_lookback_start(
        reference_time=now,
        lookback_hours=thresholds.lookback_hours,
    )
    normalized_ticker = ticker.strip().upper()

    filtered_articles = [
        article
        for article in recent_articles
        if article.ticker == normalized_ticker
        and article.analyzed_at.astimezone(timezone.utc) >= lookback_start
        and article.analyzed_at.astimezone(timezone.utc) <= now
    ]

    if len(filtered_articles) < thresholds.min_articles:
        distribution = _build_distribution(filtered_articles)
        reasons = [
            _build_reason(
                code=TickerMixedReasonCode.SPARSE_DATA,
                triggered=True,
                value=float(len(filtered_articles)),
                threshold=float(thresholds.min_articles),
                message="Not enough recent articles are available for ticker-level mixed detection.",
            )
        ]
        return TickerMixedDetectionResult(
            ticker=normalized_ticker,
            status=MixedStatus.INSUFFICIENT_DATA,
            is_mixed=False,
            article_count=len(filtered_articles),
            lookback_start=lookback_start,
            lookback_end=now,
            mean_score=None,
            score_stddev=None,
            sentiment_distribution=distribution,
            positive_ratio=None,
            negative_ratio=None,
            triggered_reason_codes=[TickerMixedReasonCode.SPARSE_DATA],
            reasons=reasons,
            thresholds=thresholds,
            recent_articles=filtered_articles,
        )

    scores = [article.score for article in filtered_articles]
    mean_score = sum(scores) / len(scores)
    score_stddev = _calculate_stddev(scores)
    distribution = _build_distribution(filtered_articles)
    total_count = distribution.total_count
    positive_ratio = distribution.positive_count / total_count if total_count else 0.0
    negative_ratio = distribution.negative_count / total_count if total_count else 0.0

    triggered_codes: list[TickerMixedReasonCode] = []
    reasons: list[MixedReason] = []

    high_variance = score_stddev >= thresholds.score_stddev_threshold
    reasons.append(
        _build_reason(
            code=TickerMixedReasonCode.HIGH_SCORE_VARIANCE,
            triggered=high_variance,
            value=score_stddev,
            threshold=thresholds.score_stddev_threshold,
            message=(
                "Recent article sentiment scores vary widely for this ticker."
                if high_variance
                else "Recent article sentiment scores are relatively consistent."
            ),
        )
    )
    if high_variance:
        triggered_codes.append(TickerMixedReasonCode.HIGH_SCORE_VARIANCE)

    conflicting_distribution = (
        positive_ratio >= thresholds.opposing_side_ratio_threshold
        and negative_ratio >= thresholds.opposing_side_ratio_threshold
    )
    reasons.append(
        _build_reason(
            code=TickerMixedReasonCode.CONFLICTING_DISTRIBUTION,
            triggered=conflicting_distribution,
            value=min(positive_ratio, negative_ratio),
            threshold=thresholds.opposing_side_ratio_threshold,
            message=(
                "Recent article labels include meaningful positive and negative camps."
                if conflicting_distribution
                else "Recent article labels do not show a strong positive-vs-negative split."
            ),
        )
    )
    if conflicting_distribution:
        triggered_codes.append(TickerMixedReasonCode.CONFLICTING_DISTRIBUTION)

    is_mixed = len(triggered_codes) >= thresholds.min_trigger_count
    return TickerMixedDetectionResult(
        ticker=normalized_ticker,
        status=MixedStatus.MIXED if is_mixed else MixedStatus.CLEAR,
        is_mixed=is_mixed,
        article_count=len(filtered_articles),
        lookback_start=lookback_start,
        lookback_end=now,
        mean_score=round(mean_score, 4),
        score_stddev=round(score_stddev, 4),
        sentiment_distribution=distribution,
        positive_ratio=round(positive_ratio, 4),
        negative_ratio=round(negative_ratio, 4),
        triggered_reason_codes=triggered_codes,
        reasons=reasons,
        thresholds=thresholds,
        recent_articles=filtered_articles,
    )


def _build_reason(
    *,
    code: ArticleMixedReasonCode | TickerMixedReasonCode,
    triggered: bool,
    value: float | None,
    threshold: float | None,
    message: str,
) -> MixedReason:
    return MixedReason(
        code=code,
        triggered=triggered,
        value=round(value, 4) if value is not None else None,
        threshold=round(threshold, 4) if threshold is not None else None,
        message=message,
    )


def _calculate_stddev(values: list[float]) -> float:
    if not values:
        return 0.0
    mean_value = sum(values) / len(values)
    variance = sum((value - mean_value) ** 2 for value in values) / len(values)
    return sqrt(variance)


def _build_distribution(
    articles: list[TickerSentimentObservation],
) -> TickerSentimentDistribution:
    counts = Counter(article.label for article in articles)
    return TickerSentimentDistribution(
        positive_count=counts.get(FinBERTSentimentLabel.POSITIVE, 0),
        neutral_count=counts.get(FinBERTSentimentLabel.NEUTRAL, 0),
        negative_count=counts.get(FinBERTSentimentLabel.NEGATIVE, 0),
    )