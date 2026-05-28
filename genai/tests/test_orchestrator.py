from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace

from app.repositories import InMemoryEnrichmentRepository
from app.schemas.article_fetch import (
    ArticleFetchFailureCategory,
    ArticleFetchStatus,
)
from app.schemas.enrichment import ArticleEnrichmentRequest
from app.schemas.mixed import (
    ArticleMixedConfig,
    ArticleMixedDetectionResult,
    MixedStatus,
    TickerMixedConfig,
    TickerMixedDetectionResult,
    TickerSentimentDistribution,
)
from app.schemas.sentiment import (
    AggregationStrategy,
    ChunkSentimentResult,
    FinBERTSentimentLabel,
    SentimentChunkSource,
    SentimentProbabilities,
    SentimentResult,
)
from app.schemas.storage import AnalysisOutcome, AnalysisStatus
from app.schemas.xai import XAIResult
from app.services.orchestrator import pipeline as pipeline_module
from app.services.orchestrator.pipeline import EnrichmentOrchestrator


def test_orchestrator_requires_direct_text_when_remote_fetch_disabled() -> None:
    request = ArticleEnrichmentRequest(
        news_id="blocked-yahoo-news-1",
        title="Yahoo Finance article",
        link="https://finance.yahoo.com/news/example-article",
        ticker=["AAPL"],
    )

    result = EnrichmentOrchestrator(
        repository=InMemoryEnrichmentRepository()
    ).run(request)

    assert result.analysis_status == AnalysisStatus.FETCH_FAILED
    assert result.analysis_outcome == AnalysisOutcome.FATAL_FAILURE
    assert result.fetch_result is not None
    assert result.fetch_result.fetch_status == ArticleFetchStatus.FETCH_FAILED
    assert result.fetch_result.retryable is False
    assert result.fetch_result.failure_category == ArticleFetchFailureCategory.ACCESS_BLOCKED
    assert "Remote URL crawling has been removed" in (result.fetch_result.error_message or "")


def test_orchestrator_marks_partial_failure_when_xai_stage_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.orchestrator.pipeline.clean_article_text",
        lambda text: "Revenue rose 12% year over year. Margins improved in the quarter. Outlook was raised for the year.",
    )
    monkeypatch.setattr(
        "app.services.orchestrator.pipeline.validate_article_text",
        lambda text, **kwargs: SimpleNamespace(
            is_valid=True,
            reason=None,
            word_count=16,
            character_count=len(text),
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator.pipeline.summarize_to_three_lines_result",
        lambda title, article_text: SimpleNamespace(
            lines=["line 1", "line 2", "line 3"],
            failure_code=None,
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator.pipeline.analyze_sentiment",
        lambda title, article_text: SentimentResult(
            label=FinBERTSentimentLabel.POSITIVE,
            score=62.0,
            confidence=0.84,
            probabilities=SentimentProbabilities(
                positive=0.8,
                neutral=0.15,
                negative=0.05,
            ),
            aggregation_strategy=AggregationStrategy.WEIGHTED_MEAN,
            chunk_results=[
                ChunkSentimentResult(
                    chunk_index=0,
                    source=SentimentChunkSource.BODY,
                    text="Revenue rose 12% year over year.",
                    token_count=18,
                    weight=1.0,
                    label=FinBERTSentimentLabel.POSITIVE,
                    score=62.0,
                    confidence=0.84,
                    probabilities=SentimentProbabilities(
                        positive=0.8,
                        neutral=0.15,
                        negative=0.05,
                    ),
                )
            ],
            disagreement_ratio=0.0,
            chunk_count=1,
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator.pipeline.explain_sentiment",
        lambda title, article_text, sentiment_result=None: (_ for _ in ()).throw(
            RuntimeError("xai unavailable")
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator.pipeline.detect_article_level_mixed",
        lambda sentiment_result: ArticleMixedDetectionResult(
            status=MixedStatus.CLEAR,
            is_mixed=False,
            has_conflicting_signals=False,
            dominant_sentiment=FinBERTSentimentLabel.POSITIVE,
            score=sentiment_result.score,
            confidence=sentiment_result.confidence,
            disagreement_ratio=sentiment_result.disagreement_ratio,
            triggered_reason_codes=[],
            reasons=[],
            thresholds=ArticleMixedConfig(),
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator.pipeline.detect_ticker_level_mixed",
        lambda **kwargs: TickerMixedDetectionResult(
            ticker="AAPL",
            status=MixedStatus.INSUFFICIENT_DATA,
            is_mixed=False,
            article_count=1,
            lookback_start=datetime.now(timezone.utc),
            lookback_end=datetime.now(timezone.utc),
            mean_score=62.0,
            score_stddev=0.0,
            sentiment_distribution=TickerSentimentDistribution(
                positive_count=1,
                neutral_count=0,
                negative_count=0,
            ),
            positive_ratio=1.0,
            negative_ratio=0.0,
            triggered_reason_codes=[],
            reasons=[],
            thresholds=TickerMixedConfig(),
            recent_articles=[],
        ),
    )

    repository = InMemoryEnrichmentRepository()
    orchestrator = EnrichmentOrchestrator(repository=repository, include_xai=True)
    request = ArticleEnrichmentRequest(
        news_id="news-1",
        title="Revenue rises on stronger demand",
        link="https://example.com/news/1",
        ticker=["AAPL"],
    )

    payload = orchestrator.run_with_text(
        request,
        article_text="Revenue rose 12% year over year. Margins improved in the quarter.",
    )

    assert payload.analysis_status == AnalysisStatus.XAI_FAILED
    assert payload.analysis_outcome == AnalysisOutcome.PARTIAL_SUCCESS
    assert any(
        stage.stage.value == "xai" and stage.status.value == "failed"
        for stage in payload.stage_statuses
    )
    assert any("xai unavailable" in error.message.lower() for error in payload.errors)
    assert payload.sentiment is not None
    assert payload.article_mixed is not None


def test_orchestrator_skips_xai_in_base_pipeline_by_default(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.orchestrator.pipeline.clean_article_text",
        lambda text: "Revenue rose 12% year over year. Margins improved in the quarter. Outlook was raised for the year.",
    )
    monkeypatch.setattr(
        "app.services.orchestrator.pipeline.validate_article_text",
        lambda text, **kwargs: SimpleNamespace(
            is_valid=True,
            reason=None,
            word_count=16,
            character_count=len(text),
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator.pipeline.summarize_to_three_lines_result",
        lambda title, article_text: SimpleNamespace(
            lines=["line 1", "line 2", "line 3"],
            failure_code=None,
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator.pipeline.analyze_sentiment",
        lambda title, article_text: SentimentResult(
            label=FinBERTSentimentLabel.POSITIVE,
            score=62.0,
            confidence=0.84,
            probabilities=SentimentProbabilities(
                positive=0.8,
                neutral=0.15,
                negative=0.05,
            ),
            aggregation_strategy=AggregationStrategy.WEIGHTED_MEAN,
            chunk_results=[
                ChunkSentimentResult(
                    chunk_index=0,
                    source=SentimentChunkSource.BODY,
                    text="Revenue rose 12% year over year.",
                    token_count=18,
                    weight=1.0,
                    label=FinBERTSentimentLabel.POSITIVE,
                    score=62.0,
                    confidence=0.84,
                    probabilities=SentimentProbabilities(
                        positive=0.8,
                        neutral=0.15,
                        negative=0.05,
                    ),
                )
            ],
            disagreement_ratio=0.0,
            chunk_count=1,
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator.pipeline.explain_sentiment",
        lambda title, article_text, sentiment_result=None: (_ for _ in ()).throw(
            AssertionError("Base pipeline should not call XAI when inline XAI is disabled.")
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator.pipeline.detect_article_level_mixed",
        lambda sentiment_result: ArticleMixedDetectionResult(
            status=MixedStatus.CLEAR,
            is_mixed=False,
            has_conflicting_signals=False,
            dominant_sentiment=FinBERTSentimentLabel.POSITIVE,
            score=sentiment_result.score,
            confidence=sentiment_result.confidence,
            disagreement_ratio=sentiment_result.disagreement_ratio,
            triggered_reason_codes=[],
            reasons=[],
            thresholds=ArticleMixedConfig(),
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator.pipeline.detect_ticker_level_mixed",
        lambda **kwargs: TickerMixedDetectionResult(
            ticker="AAPL",
            status=MixedStatus.INSUFFICIENT_DATA,
            is_mixed=False,
            article_count=1,
            lookback_start=datetime.now(timezone.utc),
            lookback_end=datetime.now(timezone.utc),
            mean_score=62.0,
            score_stddev=0.0,
            sentiment_distribution=TickerSentimentDistribution(
                positive_count=1,
                neutral_count=0,
                negative_count=0,
            ),
            positive_ratio=1.0,
            negative_ratio=0.0,
            triggered_reason_codes=[],
            reasons=[],
            thresholds=TickerMixedConfig(),
            recent_articles=[],
        ),
    )

    repository = InMemoryEnrichmentRepository()
    orchestrator = EnrichmentOrchestrator(repository=repository, include_xai=False)
    request = ArticleEnrichmentRequest(
        news_id="news-2",
        title="Revenue rises on stronger demand",
        link="https://example.com/news/2",
        ticker=["AAPL"],
    )

    payload = orchestrator.run_with_text(
        request,
        article_text="Revenue rose 12% year over year. Margins improved in the quarter.",
    )

    assert payload.analysis_status == AnalysisStatus.COMPLETED
    assert payload.analysis_outcome == AnalysisOutcome.SUCCESS
    assert payload.xai is None
    assert any(
        stage.stage.value == "xai" and stage.status.value == "skipped"
        for stage in payload.stage_statuses
    )


def test_orchestrator_skips_xai_when_backend_is_disabled(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.orchestrator.pipeline.clean_article_text",
        lambda text: "Revenue rose 12% year over year. Margins improved in the quarter. Outlook was raised for the year.",
    )
    monkeypatch.setattr(
        "app.services.orchestrator.pipeline.validate_article_text",
        lambda text, **kwargs: SimpleNamespace(
            is_valid=True,
            reason=None,
            word_count=16,
            character_count=len(text),
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator.pipeline.summarize_to_three_lines_result",
        lambda title, article_text: SimpleNamespace(
            lines=["line 1", "line 2", "line 3"],
            failure_code=None,
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator.pipeline.analyze_sentiment",
        lambda title, article_text: SentimentResult(
            label=FinBERTSentimentLabel.POSITIVE,
            score=62.0,
            confidence=0.84,
            probabilities=SentimentProbabilities(
                positive=0.8,
                neutral=0.15,
                negative=0.05,
            ),
            aggregation_strategy=AggregationStrategy.WEIGHTED_MEAN,
            chunk_results=[
                ChunkSentimentResult(
                    chunk_index=0,
                    source=SentimentChunkSource.BODY,
                    text="Revenue rose 12% year over year.",
                    token_count=18,
                    weight=1.0,
                    label=FinBERTSentimentLabel.POSITIVE,
                    score=62.0,
                    confidence=0.84,
                    probabilities=SentimentProbabilities(
                        positive=0.8,
                        neutral=0.15,
                        negative=0.05,
                    ),
                )
            ],
            disagreement_ratio=0.0,
            chunk_count=1,
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator.pipeline.is_xai_backend_disabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "app.services.orchestrator.pipeline.explain_sentiment",
        lambda title, article_text, sentiment_result=None: (_ for _ in ()).throw(
            AssertionError("Disabled XAI backend should skip before explain_sentiment is called.")
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator.pipeline.detect_article_level_mixed",
        lambda sentiment_result: ArticleMixedDetectionResult(
            status=MixedStatus.CLEAR,
            is_mixed=False,
            has_conflicting_signals=False,
            dominant_sentiment=FinBERTSentimentLabel.POSITIVE,
            score=sentiment_result.score,
            confidence=sentiment_result.confidence,
            disagreement_ratio=sentiment_result.disagreement_ratio,
            triggered_reason_codes=[],
            reasons=[],
            thresholds=ArticleMixedConfig(),
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator.pipeline.detect_ticker_level_mixed",
        lambda **kwargs: TickerMixedDetectionResult(
            ticker="AAPL",
            status=MixedStatus.INSUFFICIENT_DATA,
            is_mixed=False,
            article_count=1,
            lookback_start=datetime.now(timezone.utc),
            lookback_end=datetime.now(timezone.utc),
            mean_score=62.0,
            score_stddev=0.0,
            sentiment_distribution=TickerSentimentDistribution(
                positive_count=1,
                neutral_count=0,
                negative_count=0,
            ),
            positive_ratio=1.0,
            negative_ratio=0.0,
            triggered_reason_codes=[],
            reasons=[],
            thresholds=TickerMixedConfig(),
            recent_articles=[],
        ),
    )

    repository = InMemoryEnrichmentRepository()
    orchestrator = EnrichmentOrchestrator(repository=repository, include_xai=True)
    request = ArticleEnrichmentRequest(
        news_id="news-3",
        title="Revenue rises on stronger demand",
        link="https://example.com/news/3",
        ticker=["AAPL"],
    )

    payload = orchestrator.run_with_text(
        request,
        article_text="Revenue rose 12% year over year. Margins improved in the quarter.",
    )

    assert payload.analysis_status == AnalysisStatus.COMPLETED
    assert payload.analysis_outcome == AnalysisOutcome.SUCCESS
    assert payload.xai is None
    assert any(
        stage.stage.value == "xai" and stage.status.value == "skipped"
        for stage in payload.stage_statuses
    )


def test_orchestrator_keeps_xai_when_summary_generation_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.orchestrator.pipeline.clean_article_text",
        lambda text: (
            "Revenue rose 12% year over year. Margins improved in the quarter. "
            "Outlook was raised for the year."
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator.pipeline.validate_article_text",
        lambda text, **kwargs: SimpleNamespace(
            is_valid=True,
            reason=None,
            word_count=16,
            character_count=len(text),
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator.pipeline.summarize_to_three_lines_result",
        lambda title, article_text: SimpleNamespace(
            lines=["", "", ""],
            failure_code="invalid_shape",
        ),
    )
    sentiment_result = SentimentResult(
        label=FinBERTSentimentLabel.POSITIVE,
        score=62.0,
        confidence=0.84,
        probabilities=SentimentProbabilities(
            positive=0.8,
            neutral=0.15,
            negative=0.05,
        ),
        aggregation_strategy=AggregationStrategy.WEIGHTED_MEAN,
        chunk_results=[
            ChunkSentimentResult(
                chunk_index=0,
                source=SentimentChunkSource.BODY,
                text="Revenue rose 12% year over year.",
                token_count=18,
                weight=1.0,
                label=FinBERTSentimentLabel.POSITIVE,
                score=62.0,
                confidence=0.84,
                probabilities=SentimentProbabilities(
                    positive=0.8,
                    neutral=0.15,
                    negative=0.05,
                ),
            )
        ],
        disagreement_ratio=0.0,
        chunk_count=1,
    )
    monkeypatch.setattr(
        "app.services.orchestrator.pipeline.analyze_sentiment",
        lambda title, article_text: sentiment_result,
    )
    monkeypatch.setattr(
        "app.services.orchestrator.pipeline.explain_sentiment",
        lambda title, article_text, sentiment_result=None: XAIResult(
            target_label=FinBERTSentimentLabel.POSITIVE,
            explanation_method="attention_sentence",
            explained_unit="sentence",
            highlights=[],
            limitations=[],
            sentence_count=3,
            truncated=False,
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator.pipeline.detect_article_level_mixed",
        lambda sentiment_result: ArticleMixedDetectionResult(
            status=MixedStatus.CLEAR,
            is_mixed=False,
            has_conflicting_signals=False,
            dominant_sentiment=FinBERTSentimentLabel.POSITIVE,
            score=sentiment_result.score,
            confidence=sentiment_result.confidence,
            disagreement_ratio=sentiment_result.disagreement_ratio,
            triggered_reason_codes=[],
            reasons=[],
            thresholds=ArticleMixedConfig(),
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator.pipeline.detect_ticker_level_mixed",
        lambda **kwargs: TickerMixedDetectionResult(
            ticker="AAPL",
            status=MixedStatus.INSUFFICIENT_DATA,
            is_mixed=False,
            article_count=1,
            lookback_start=datetime.now(timezone.utc),
            lookback_end=datetime.now(timezone.utc),
            mean_score=62.0,
            score_stddev=0.0,
            sentiment_distribution=TickerSentimentDistribution(
                positive_count=1,
                neutral_count=0,
                negative_count=0,
            ),
            positive_ratio=1.0,
            negative_ratio=0.0,
            triggered_reason_codes=[],
            reasons=[],
            thresholds=TickerMixedConfig(),
            recent_articles=[],
        ),
    )

    repository = InMemoryEnrichmentRepository()
    orchestrator = EnrichmentOrchestrator(repository=repository, include_xai=True)
    request = ArticleEnrichmentRequest(
        news_id="news-summary-fail-xai-1",
        title="Revenue rises on stronger demand",
        link="https://example.com/news/summary-fail",
        ticker=["AAPL"],
    )

    payload = orchestrator.run_with_text(
        request,
        article_text="Revenue rose 12% year over year. Margins improved in the quarter.",
    )

    assert payload.analysis_status == AnalysisStatus.COMPLETED_WITH_PARTIAL_RESULTS
    assert payload.analysis_outcome == AnalysisOutcome.PARTIAL_SUCCESS
    assert payload.failure_code == "summary_generation_failed"
    assert payload.summary_3lines == []
    assert payload.sentiment is not None
    assert payload.xai is not None
    assert any(
        stage.stage.value == "summarize" and stage.status.value == "failed"
        for stage in payload.stage_statuses
    )
    assert any(
        stage.stage.value == "xai" and stage.status.value == "completed"
        for stage in payload.stage_statuses
    )


def test_orchestrator_preserves_original_text_when_clean_result_is_empty(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.orchestrator.pipeline.clean_article_text",
        lambda text: "   ",
    )

    repository = InMemoryEnrichmentRepository()
    orchestrator = EnrichmentOrchestrator(repository=repository, include_xai=True)
    request = ArticleEnrichmentRequest(
        news_id="news-filtered-clean",
        title="Transcript only page",
        link="https://example.com/news/filtered-clean",
        ticker=["AAPL"],
    )

    payload = orchestrator.run_with_text(
        request,
        article_text="raw text that gets filtered",
    )

    assert payload.analysis_status != AnalysisStatus.CLEAN_FILTERED
    assert payload.analysis_outcome != AnalysisOutcome.FILTERED
    assert payload.cleaned_text_available is True
    assert any(
        stage.stage.value == "clean" and stage.status.value == "completed"
        for stage in payload.stage_statuses
    )


def test_orchestrator_bypasses_strict_validate_filter_to_preserve_article(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.orchestrator.pipeline.clean_article_text",
        lambda text: "short cleaned text",
    )
    monkeypatch.setattr(
        "app.services.orchestrator.pipeline.validate_article_text",
        lambda text, **kwargs: SimpleNamespace(
            is_valid=False,
            reason="Article text is too short after cleaning.",
            word_count=3,
            character_count=len(text),
        ),
    )

    repository = InMemoryEnrichmentRepository()
    orchestrator = EnrichmentOrchestrator(repository=repository, include_xai=True)
    request = ArticleEnrichmentRequest(
        news_id="news-filtered-validate",
        title="Insufficient body",
        link="https://example.com/news/filtered-validate",
        ticker=["AAPL"],
    )

    payload = orchestrator.run_with_text(
        request,
        article_text="short text",
    )

    assert payload.analysis_status != AnalysisStatus.VALIDATE_FILTERED
    assert payload.analysis_outcome != AnalysisOutcome.FILTERED
    assert any(
        stage.stage.value == "validate" and stage.status.value == "completed"
        for stage in payload.stage_statuses
    )


def test_orchestrator_skips_sentiment_when_text_exceeds_sentiment_limit(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.orchestrator.pipeline.settings",
        replace(
            pipeline_module.settings,
            sentiment_max_input_chars=10,
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator.pipeline.analyze_sentiment",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("Sentiment should be skipped before FinBERT call.")
        ),
    )

    repository = InMemoryEnrichmentRepository()
    orchestrator = EnrichmentOrchestrator(repository=repository, include_xai=True)
    request = ArticleEnrichmentRequest(
        news_id="news-sentiment-skip-limit",
        title="Long text sentiment guard",
        link="https://example.com/news/sentiment-skip-limit",
        ticker=["AAPL"],
    )

    payload = orchestrator.run_with_text(
        request,
        article_text="This article body is intentionally longer than ten characters.",
    )

    sentiment_stage = next(
        stage for stage in payload.stage_statuses if stage.stage.value == "sentiment"
    )
    assert sentiment_stage.status.value == "failed"
    assert "exceeded the configured limit" in (sentiment_stage.message or "")


def test_orchestrator_skips_xai_when_text_exceeds_xai_limit(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.orchestrator.pipeline.settings",
        replace(
            pipeline_module.settings,
            sentiment_max_input_chars=5000,
            xai_max_input_chars=10,
        ),
    )
    monkeypatch.setattr(
        "app.services.orchestrator.pipeline.analyze_sentiment",
        lambda **kwargs: SentimentResult(
            label=FinBERTSentimentLabel.POSITIVE,
            score=40.0,
            confidence=0.7,
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
        "app.services.orchestrator.pipeline.explain_sentiment",
        lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("XAI should be skipped before explain_sentiment call.")
        ),
    )

    repository = InMemoryEnrichmentRepository()
    orchestrator = EnrichmentOrchestrator(repository=repository, include_xai=True)
    request = ArticleEnrichmentRequest(
        news_id="news-xai-skip-limit",
        title="Long text xai guard",
        link="https://example.com/news/xai-skip-limit",
        ticker=["AAPL"],
    )

    payload = orchestrator.run_with_text(
        request,
        article_text="This article body is intentionally longer than ten characters.",
    )

    xai_stage = next(stage for stage in payload.stage_statuses if stage.stage.value == "xai")
    assert xai_stage.status.value == "skipped"
    assert "exceeded the configured limit" in (xai_stage.message or "")