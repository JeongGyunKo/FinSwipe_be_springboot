from __future__ import annotations

from dataclasses import replace

from app.schemas.enrichment import SentimentLabel, SentimentResult
from app.services import enrichment_service as enrichment_service_module


def _sentiment(label: SentimentLabel, confidence: float = 0.8) -> SentimentResult:
    return SentimentResult(label=label, score=0.42, confidence=confidence)


def test_alert_decision_all_mode_sends_when_alerts_enabled(monkeypatch) -> None:
    monkeypatch.setattr(
        enrichment_service_module,
        "settings",
        replace(
            enrichment_service_module.settings,
            alerts_enabled=True,
            sentiment_only_alerts=False,
            sentiment_alert_min_confidence=0.45,
        ),
    )

    decision = enrichment_service_module._build_alert_decision(_sentiment(SentimentLabel.NEUTRAL))

    assert decision.should_send is True
    assert decision.mode.value == "all"
    assert decision.reason_code == "all_alerts_enabled"


def test_alert_decision_sentiment_only_filters_neutral(monkeypatch) -> None:
    monkeypatch.setattr(
        enrichment_service_module,
        "settings",
        replace(
            enrichment_service_module.settings,
            alerts_enabled=True,
            sentiment_only_alerts=True,
            sentiment_alert_min_confidence=0.45,
        ),
    )

    decision = enrichment_service_module._build_alert_decision(_sentiment(SentimentLabel.NEUTRAL))

    assert decision.should_send is False
    assert decision.mode.value == "sentiment_only"
    assert decision.reason_code == "sentiment_neutral_filtered"


def test_alert_decision_sentiment_only_requires_confidence(monkeypatch) -> None:
    monkeypatch.setattr(
        enrichment_service_module,
        "settings",
        replace(
            enrichment_service_module.settings,
            alerts_enabled=True,
            sentiment_only_alerts=True,
            sentiment_alert_min_confidence=0.60,
        ),
    )

    decision = enrichment_service_module._build_alert_decision(
        _sentiment(SentimentLabel.BULLISH, confidence=0.55)
    )

    assert decision.should_send is False
    assert decision.reason_code == "sentiment_confidence_low"


def test_alert_decision_sentiment_only_allows_bullish_bearish(monkeypatch) -> None:
    monkeypatch.setattr(
        enrichment_service_module,
        "settings",
        replace(
            enrichment_service_module.settings,
            alerts_enabled=True,
            sentiment_only_alerts=True,
            sentiment_alert_min_confidence=0.45,
        ),
    )

    bullish = enrichment_service_module._build_alert_decision(
        _sentiment(SentimentLabel.BULLISH, confidence=0.8)
    )
    bearish = enrichment_service_module._build_alert_decision(
        _sentiment(SentimentLabel.BEARISH, confidence=0.8)
    )

    assert bullish.should_send is True
    assert bullish.reason_code == "sentiment_label_allowed"
    assert bearish.should_send is True
    assert bearish.reason_code == "sentiment_label_allowed"


def test_news_power_score_uses_absolute_sentiment_and_confidence() -> None:
    positive = enrichment_service_module._build_news_power_score(
        SentimentResult(label=SentimentLabel.BULLISH, score=0.8, confidence=0.75)
    )
    negative = enrichment_service_module._build_news_power_score(
        SentimentResult(label=SentimentLabel.BEARISH, score=-0.8, confidence=0.75)
    )
    neutral = enrichment_service_module._build_news_power_score(
        SentimentResult(label=SentimentLabel.NEUTRAL, score=0.05, confidence=0.6)
    )

    assert positive == 0.6
    assert negative == 0.6
    assert neutral == 0.03
    assert enrichment_service_module._build_news_power_score(None) is None