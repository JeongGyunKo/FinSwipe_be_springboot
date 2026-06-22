from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import uuid4

from app.core import get_settings
from app.core.logging import get_logger, log_event
from app.repositories import EnrichmentRepository, SaveEnrichmentRequest
from app.schemas.article_fetch import (
    ArticleFetchFailureCategory,
    ArticleFetchResult,
    ArticleFetchStatus,
)
from app.schemas.article_fetch import ArticleTextSource
from app.schemas.enrichment import ArticleEnrichmentRequest
from app.schemas.mixed import TickerSentimentObservation
from app.schemas.sentiment import SentimentResult
from app.schemas.storage import (
    AnalysisStatus,
    EnrichmentStoragePayload,
    PipelineStageName,
)
from app.services.gemini import gemini_log_context
from app.services.mixed_detector import (
    detect_article_level_mixed,
    detect_ticker_level_mixed,
)
from app.services.orchestrator.status_tracker import PipelineStatusTracker
from app.services.payload_builder import build_enrichment_storage_payload
from app.services.sentiment import analyze_sentiment
from app.services.text_cleaner import clean_article_text, validate_article_text
from app.services.xai import explain_sentiment, is_xai_backend_disabled


logger = get_logger(__name__)
settings = get_settings()


class EnrichmentOrchestrator:
    """Compose the full article enrichment pipeline into one storage-ready payload."""

    def __init__(
        self,
        *,
        repository: EnrichmentRepository,
        include_xai: bool | None = None,
    ) -> None:
        self._repository = repository
        self._include_xai = settings.enable_inline_xai if include_xai is None else include_xai

    def run(self, request: ArticleEnrichmentRequest) -> EnrichmentStoragePayload:
        pipeline_trace_id = str(uuid4())
        with gemini_log_context(
            news_id=request.news_id,
            link=str(request.link),
            source=request.source,
            tickers=request.ticker,
            pipeline_trace_id=pipeline_trace_id,
        ):
            return self._run_pipeline(
                request=request,
                provided_text=None,
                pipeline_trace_id=pipeline_trace_id,
            )

    def run_with_text(
        self,
        request: ArticleEnrichmentRequest,
        *,
        article_text: str | None = None,
        summary_text: str | None = None,
    ) -> EnrichmentStoragePayload:
        provided_text = (article_text or "").strip() or (summary_text or "").strip() or None
        pipeline_trace_id = str(uuid4())
        with gemini_log_context(
            news_id=request.news_id,
            link=str(request.link),
            source=request.source,
            tickers=request.ticker,
            pipeline_trace_id=pipeline_trace_id,
            text_source=(
                ArticleTextSource.PROVIDED_ARTICLE_TEXT.value
                if article_text and article_text.strip()
                else ArticleTextSource.PROVIDED_SUMMARY_TEXT.value
            ) if provided_text is not None else None,
        ):
            return self._run_pipeline(
                request=request,
                provided_text=provided_text,
                pipeline_trace_id=pipeline_trace_id,
                text_source=(
                    ArticleTextSource.PROVIDED_ARTICLE_TEXT
                    if article_text and article_text.strip()
                    else ArticleTextSource.PROVIDED_SUMMARY_TEXT
                ) if provided_text is not None else None,
            )

    def _run_pipeline(
        self,
        *,
        request: ArticleEnrichmentRequest,
        provided_text: str | None,
        pipeline_trace_id: str,
        text_source: ArticleTextSource | None = None,
    ) -> EnrichmentStoragePayload:
        analyzed_at = datetime.now(timezone.utc)
        tracker = PipelineStatusTracker()
        log_event(
            logger,
            logging.INFO,
            "enrichment_started",
            news_id=request.news_id,
            pipeline_trace_id=pipeline_trace_id,
            link=str(request.link),
            tickers=request.ticker,
        )

        fetch_result = self._run_fetch_stage(
            request=request,
            tracker=tracker,
            provided_text=provided_text,
            text_source=text_source,
        )
        cleaned_text = ""
        summary_3lines: list[str] | None = None
        sentiment_result = None
        xai_result = None
        sentiment_reason: str | None = None
        event_category: str | None = None
        sentiment_divergence: bool | None = None
        article_mixed = None
        ticker_mixed = None
        headline_ko: str | None = None

        if fetch_result.fetch_status == ArticleFetchStatus.SUCCESS:
            cleaned_text, can_continue = self._run_clean_and_validate(
                fetch_result=fetch_result,
                tracker=tracker,
            )

            if can_continue:
                sentiment_result = self._run_sentiment_stage(
                    request=request,
                    cleaned_text=cleaned_text,
                    tracker=tracker,
                )
                if sentiment_result is not None:
                    sentiment_divergence = _compute_sentiment_divergence(sentiment_result)

                    if self._include_xai:
                        xai_result = self._run_xai_stage(
                            request=request,
                            cleaned_text=cleaned_text,
                            sentiment_result=sentiment_result,
                            tracker=tracker,
                        )
                    else:
                        tracker.skip(
                            PipelineStageName.XAI,
                            "XAI disabled — using sentiment_reason instead.",
                        )

                    # 통합 분석: Gemini 1회 호출로 요약·감성이유·이벤트분류·헤드라인번역 동시 처리
                    unified = self._run_unified_analysis_stage(
                        request=request,
                        cleaned_text=cleaned_text,
                        sentiment_result=sentiment_result,
                        tracker=tracker,
                    )
                    sentiment_reason = unified.get("sentiment_reason")
                    event_category = unified.get("event_category")
                    headline_ko = unified.get("headline_ko")
                    unified_summary = unified.get("summary_3lines")
                    if unified_summary:
                        summary_3lines = unified_summary

                    article_mixed, ticker_mixed = self._run_mixed_detection_stage(
                        request=request,
                        sentiment_result=sentiment_result,
                        analyzed_at=analyzed_at,
                        tracker=tracker,
                    )
                else:
                    tracker.skip(
                        PipelineStageName.XAI,
                        "Skipped because sentiment analysis did not produce a result.",
                    )
                    tracker.skip(
                        PipelineStageName.MIXED_DETECTION,
                        "Skipped because sentiment analysis did not produce a result.",
                    )
                    headline_ko = None
        else:
            self._skip_after_fetch_failure(tracker)

        payload = self._build_payload(
            request=request,
            analyzed_at=analyzed_at,
            pipeline_trace_id=pipeline_trace_id,
            tracker=tracker,
            fetch_result=fetch_result,
            cleaned_text=cleaned_text,
            summary_3lines=summary_3lines,
            sentiment_result=sentiment_result,
            xai_result=xai_result,
            sentiment_reason=sentiment_reason,
            event_category=event_category,
            sentiment_divergence=sentiment_divergence,
            article_mixed=article_mixed,
            ticker_mixed=ticker_mixed,
            headline_ko=headline_ko,
        )
        final_payload = self._persist_payload(
            request=request,
            payload=payload,
            tracker=tracker,
        )
        log_event(
            logger,
            logging.INFO,
            "enrichment_finished",
            news_id=request.news_id,
            pipeline_trace_id=pipeline_trace_id,
            analysis_status=final_payload.analysis_status.value,
            analysis_outcome=final_payload.analysis_outcome.value,
            error_count=len(final_payload.errors),
        )
        return final_payload

    def _run_fetch_stage(
        self,
        *,
        request: ArticleEnrichmentRequest,
        tracker: PipelineStatusTracker,
        provided_text: str | None = None,
        text_source: ArticleTextSource | None = None,
    ) -> ArticleFetchResult:
        tracker.start(PipelineStageName.FETCH)
        if provided_text is not None:
            source_label = (
                "article text"
                if text_source == ArticleTextSource.PROVIDED_ARTICLE_TEXT
                else "summary text"
            )
            log_event(
                logger,
                logging.INFO,
                "article_fetch_skipped_using_provided_text",
                news_id=request.news_id,
                link=str(request.link),
                text_source=text_source.value if text_source is not None else None,
                raw_text_length=len(provided_text),
            )
            tracker.complete(
                PipelineStageName.FETCH,
                f"Skipped remote fetch and used directly supplied {source_label}.",
            )
            return ArticleFetchResult(
                link=str(request.link),
                publisher_domain=request.link.host,
                final_url=str(request.link),
                extraction_source=text_source,
                attempt_count=1,
                raw_text=provided_text,
                cleaned_text=provided_text,
                fetch_status=ArticleFetchStatus.SUCCESS,
                retryable=False,
                failure_category=None,
                error_message=None,
            )
        message = (
            "Remote URL crawling has been removed. "
            "Supply article_text (or summary_text) in the request payload."
        )
        log_event(
            logger,
            logging.WARNING,
            "article_fetch_disabled_requires_provided_text",
            news_id=request.news_id,
            link=str(request.link),
        )
        tracker.fail(
            PipelineStageName.FETCH,
            message,
            fatal=True,
        )
        return ArticleFetchResult(
            link=str(request.link),
            publisher_domain=request.link.host or "",
            final_url=str(request.link),
            raw_text="",
            cleaned_text="",
            fetch_status=ArticleFetchStatus.FETCH_FAILED,
            retryable=False,
            failure_category=ArticleFetchFailureCategory.ACCESS_BLOCKED,
            error_message=message,
        )

    def _run_clean_and_validate(
        self,
        *,
        fetch_result: ArticleFetchResult,
        tracker: PipelineStatusTracker,
    ) -> tuple[str, bool]:
        tracker.start(PipelineStageName.CLEAN)
        original_text = (fetch_result.raw_text or fetch_result.cleaned_text or "").strip()
        try:
            cleaned_text = clean_article_text(fetch_result.raw_text or fetch_result.cleaned_text)
        except Exception as exc:
            log_event(
                logger,
                logging.WARNING,
                "text_clean_failed",
                error=str(exc),
            )
            cleaned_text = original_text
            tracker.complete(
                PipelineStageName.CLEAN,
                "Text cleaning failed; preserved original article text.",
            )

        if not cleaned_text.strip() and original_text:
            log_event(
                logger,
                logging.WARNING,
                "text_clean_empty_fallback_to_original",
                cleaned_text_length=0,
                original_text_length=len(original_text),
            )
            cleaned_text = original_text
            tracker.complete(
                PipelineStageName.CLEAN,
                "Text cleaning removed too much; preserved original article text.",
            )

        if not cleaned_text.strip():
            log_event(
                logger,
                logging.INFO,
                "text_clean_filtered",
                error="No usable article text was provided.",
            )
            tracker.filter(
                PipelineStageName.CLEAN,
                "No usable article text was provided.",
            )
            tracker.skip(
                PipelineStageName.VALIDATE,
                "Skipped because no article text was available.",
            )
            self._skip_after_validation_failure(tracker)
            return "", False

        log_event(
            logger,
            logging.INFO,
            "text_clean_succeeded",
            cleaned_text_length=len(cleaned_text),
        )
        tracker.complete(PipelineStageName.CLEAN, "Article text cleaned successfully.")

        tracker.start(PipelineStageName.VALIDATE)
        validation = validate_article_text(
            cleaned_text,
            allow_brief=fetch_result.extraction_source == ArticleTextSource.PROVIDED_SUMMARY_TEXT,
        )
        if not validation.is_valid:
            log_event(
                logger,
                logging.WARNING,
                "text_validate_bypassed",
                reason=validation.reason,
                word_count=validation.word_count,
                character_count=validation.character_count,
            )
            tracker.complete(
                PipelineStageName.VALIDATE,
                (
                    "Strict validation failed, but text was preserved to avoid dropping article content. "
                    f"reason={validation.reason or 'unknown'}"
                ),
            )
            return cleaned_text, True

        log_event(
            logger,
            logging.INFO,
            "text_validate_succeeded",
            word_count=validation.word_count,
            character_count=validation.character_count,
        )
        tracker.complete(
            PipelineStageName.VALIDATE,
            "Article text passed validation checks.",
        )
        return cleaned_text, True

    def _run_sentiment_stage(
        self,
        *,
        request: ArticleEnrichmentRequest,
        cleaned_text: str,
        tracker: PipelineStatusTracker,
    ):
        tracker.start(PipelineStageName.SENTIMENT)
        if len(cleaned_text) > settings.sentiment_max_input_chars:
            message = (
                "Skipped sentiment analysis because cleaned text exceeded the configured "
                f"limit ({settings.sentiment_max_input_chars} chars)."
            )
            log_event(
                logger,
                logging.WARNING,
                "sentiment_inference_skipped_input_too_large",
                news_id=request.news_id,
                cleaned_text_length=len(cleaned_text),
                max_input_chars=settings.sentiment_max_input_chars,
            )
            tracker.fail(
                PipelineStageName.SENTIMENT,
                message,
                fatal=False,
            )
            return None
        try:
            sentiment_result = analyze_sentiment(
                title=request.title,
                article_text=cleaned_text,
            )
        except Exception as exc:
            log_event(
                logger,
                logging.ERROR,
                "sentiment_inference_failed",
                news_id=request.news_id,
                error=str(exc),
            )
            tracker.fail(
                PipelineStageName.SENTIMENT,
                f"Sentiment analysis failed: {exc}",
                fatal=False,
            )
            return None

        log_event(
            logger,
            logging.INFO,
            "sentiment_inference_succeeded",
            news_id=request.news_id,
            sentiment_label=sentiment_result.label.value,
            sentiment_score=sentiment_result.score,
            confidence=sentiment_result.confidence,
        )
        tracker.complete(
            PipelineStageName.SENTIMENT,
            "Sentiment analysis completed successfully.",
        )
        return sentiment_result

    def _run_xai_stage(
        self,
        *,
        request: ArticleEnrichmentRequest,
        cleaned_text: str,
        sentiment_result: SentimentResult,
        tracker: PipelineStatusTracker,
    ):
        tracker.start(PipelineStageName.XAI)
        if is_xai_backend_disabled():
            tracker.skip(
                PipelineStageName.XAI,
                "Skipped because the configured XAI backend is disabled.",
            )
            return None
        if len(cleaned_text) > settings.xai_max_input_chars:
            message = (
                "Skipped XAI because cleaned text exceeded the configured "
                f"limit ({settings.xai_max_input_chars} chars)."
            )
            log_event(
                logger,
                logging.WARNING,
                "xai_skipped_input_too_large",
                news_id=request.news_id,
                cleaned_text_length=len(cleaned_text),
                max_input_chars=settings.xai_max_input_chars,
            )
            tracker.skip(
                PipelineStageName.XAI,
                message,
            )
            return None
        try:
            xai_result = explain_sentiment(
                title=request.title,
                article_text=cleaned_text,
                sentiment_result=sentiment_result,
            )
        except Exception as exc:
            log_event(
                logger,
                logging.ERROR,
                "xai_failed",
                news_id=request.news_id,
                error=str(exc),
            )
            tracker.fail(
                PipelineStageName.XAI,
                f"XAI explanation failed: {exc}",
                fatal=False,
            )
            return None

        log_event(
            logger,
            logging.INFO,
            "xai_succeeded",
            news_id=request.news_id,
            highlight_count=len(xai_result.highlights),
            target_label=xai_result.target_label.value,
        )
        tracker.complete(
            PipelineStageName.XAI,
            "XAI explanation completed successfully.",
        )
        return xai_result

    def _run_mixed_detection_stage(
        self,
        *,
        request: ArticleEnrichmentRequest,
        sentiment_result,
        analyzed_at: datetime,
        tracker: PipelineStatusTracker,
    ):
        tracker.start(PipelineStageName.MIXED_DETECTION)
        article_mixed = None
        ticker_mixed = None
        failures: list[str] = []

        try:
            article_mixed = detect_article_level_mixed(sentiment_result)
        except Exception as exc:
            failures.append(f"Article-level mixed detection failed: {exc}")

        if request.ticker:
            try:
                primary_ticker = request.ticker[0]
                recent_articles = self._load_recent_ticker_articles(
                    ticker=primary_ticker,
                    request=request,
                    sentiment_result=sentiment_result,
                    analyzed_at=analyzed_at,
                )
                ticker_mixed = detect_ticker_level_mixed(
                    ticker=primary_ticker,
                    recent_articles=recent_articles,
                    reference_time=analyzed_at,
                )
            except Exception as exc:
                failures.append(f"Ticker-level mixed detection failed: {exc}")

        if failures:
            log_event(
                logger,
                logging.WARNING,
                "mixed_detection_failed",
                news_id=request.news_id,
                error=" ".join(failures),
            )
            tracker.fail(
                PipelineStageName.MIXED_DETECTION,
                " ".join(failures),
                fatal=False,
            )
        else:
            log_event(
                logger,
                logging.INFO,
                "mixed_detection_completed",
                news_id=request.news_id,
                article_is_mixed=article_mixed.is_mixed if article_mixed is not None else None,
                ticker_is_mixed=ticker_mixed.is_mixed if ticker_mixed is not None else None,
                ticker_status=ticker_mixed.status.value if ticker_mixed is not None else None,
            )
            message = (
                "Mixed detection completed successfully."
                if request.ticker
                else "Article-level mixed detection completed; ticker-level detection skipped because no ticker was provided."
            )
            tracker.complete(PipelineStageName.MIXED_DETECTION, message)

        return article_mixed, ticker_mixed

    def _run_unified_analysis_stage(
        self,
        *,
        request: ArticleEnrichmentRequest,
        cleaned_text: str,
        sentiment_result: SentimentResult,
        tracker: PipelineStatusTracker,
    ) -> dict:
        from app.services.unified_article_analyzer import analyze_article_unified
        try:
            result = analyze_article_unified(
                title=request.title,
                article_text=cleaned_text,
                sentiment_label=sentiment_result.label.value,
                sentiment_score=float(sentiment_result.score),
            )
            tracker.complete(PipelineStageName.SUMMARIZE, "통합 분석 완료 (요약·감성이유·이벤트·번역).")
            return result
        except Exception as exc:
            log_event(logger, logging.WARNING, "unified_analysis_failed", error=str(exc))
            tracker.fail(PipelineStageName.SUMMARIZE, f"통합 분석 실패: {exc}", fatal=False)
            return {}

    def _build_payload(
        self,
        *,
        request: ArticleEnrichmentRequest,
        analyzed_at: datetime,
        pipeline_trace_id: str,
        tracker: PipelineStatusTracker,
        fetch_result: ArticleFetchResult,
        cleaned_text: str,
        summary_3lines,
        sentiment_result,
        xai_result,
        sentiment_reason: str | None = None,
        event_category: str | None = None,
        sentiment_divergence: bool | None = None,
        article_mixed,
        ticker_mixed,
        headline_ko: str | None = None,
    ) -> EnrichmentStoragePayload:
        tracker.start(PipelineStageName.BUILD_PAYLOAD)
        try:
            tracker.complete(
                PipelineStageName.BUILD_PAYLOAD,
                "Final enrichment payload assembled successfully.",
            )
            analysis_status, analysis_outcome = tracker.derive_status()
            return build_enrichment_storage_payload(
                news_id=request.news_id,
                title=request.title,
                link=str(request.link),
                analysis_status=analysis_status,
                analysis_outcome=analysis_outcome,
                pipeline_trace_id=pipeline_trace_id,
                stage_statuses=tracker.snapshot_stage_statuses(),
                fetch_result=fetch_result,
                cleaned_text=cleaned_text,
                summary_3lines=summary_3lines,
                sentiment_result=sentiment_result,
                xai_result=xai_result,
                sentiment_reason=sentiment_reason,
                event_category=event_category,
                sentiment_divergence=sentiment_divergence,
                article_mixed=article_mixed,
                ticker_mixed=ticker_mixed,
                tickers=request.ticker,
                analyzed_at=analyzed_at,
                errors=tracker.errors(),
                prebuilt_headline_ko=headline_ko,
            )
        except Exception as exc:
            log_event(
                logger,
                logging.ERROR,
                "payload_build_failed",
                news_id=request.news_id,
                error=str(exc),
            )
            tracker.fail(
                PipelineStageName.BUILD_PAYLOAD,
                f"Final payload assembly failed: {exc}",
                fatal=True,
            )
            analysis_status, analysis_outcome = tracker.derive_status()
            return EnrichmentStoragePayload(
                news_id=request.news_id,
                title=request.title,
                link=str(request.link),
                summary_3lines=[],
                sentiment=None,
                xai=None,
                article_mixed=None,
                ticker_mixed=None,
                analysis_status=analysis_status,
                analysis_outcome=analysis_outcome,
                pipeline_trace_id=pipeline_trace_id,
                analyzed_at=analyzed_at,
                cleaned_text_available=bool(cleaned_text.strip()),
                fetch_result=fetch_result,
                stage_statuses=tracker.snapshot_stage_statuses(),
                errors=tracker.errors(),
            )

    def _persist_payload(
        self,
        *,
        request: ArticleEnrichmentRequest,
        payload: EnrichmentStoragePayload,
        tracker: PipelineStatusTracker,
    ) -> EnrichmentStoragePayload:
        tracker.start(PipelineStageName.PERSIST)
        tracker.complete(
            PipelineStageName.PERSIST,
            "Enrichment payload passed the persistence boundary successfully.",
        )
        analysis_status, analysis_outcome = tracker.derive_status()
        finalized_payload = payload.model_copy(
            update={
                "analysis_status": analysis_status,
                "analysis_outcome": analysis_outcome,
                "stage_statuses": tracker.snapshot_stage_statuses(),
                "errors": tracker.errors(),
            }
        )
        try:
            self._repository.save_enrichment_result(
                SaveEnrichmentRequest(
                    raw_news=request,
                    enrichment=finalized_payload,
                )
            )
        except Exception as exc:
            log_event(
                logger,
                logging.ERROR,
                "payload_persist_failed",
                news_id=request.news_id,
                error=str(exc),
            )
            tracker.fail(
                PipelineStageName.PERSIST,
                f"Persistence failed: {exc}",
                fatal=False,
            )
            analysis_status, analysis_outcome = tracker.derive_status()
            return payload.model_copy(
                update={
                    "analysis_status": analysis_status,
                    "analysis_outcome": analysis_outcome,
                    "stage_statuses": tracker.snapshot_stage_statuses(),
                    "errors": tracker.errors(),
                }
            )

        log_event(
            logger,
            logging.INFO,
            "payload_persist_succeeded",
            news_id=request.news_id,
            analysis_status=finalized_payload.analysis_status.value,
        )
        return finalized_payload

    def _load_recent_ticker_articles(
        self,
        *,
        ticker: str,
        request: ArticleEnrichmentRequest,
        sentiment_result,
        analyzed_at: datetime,
    ) -> list[TickerSentimentObservation]:
        historical_articles = self._repository.list_recent_ticker_sentiments(ticker)

        current_article = TickerSentimentObservation(
            ticker=ticker,
            news_id=request.news_id,
            score=sentiment_result.score,
            label=sentiment_result.label,
            confidence=sentiment_result.confidence,
            analyzed_at=analyzed_at,
        )

        deduplicated = {
            article.news_id: article
            for article in [*historical_articles, current_article]
        }
        return list(deduplicated.values())

    def _skip_after_fetch_failure(self, tracker: PipelineStatusTracker) -> None:
        self._skip_stages(
            tracker,
            [
                PipelineStageName.CLEAN,
                PipelineStageName.VALIDATE,
                PipelineStageName.SUMMARIZE,
                PipelineStageName.SENTIMENT,
                PipelineStageName.XAI,
                PipelineStageName.MIXED_DETECTION,
            ],
            "Skipped because article fetching failed.",
        )

    def _skip_after_validation_failure(self, tracker: PipelineStatusTracker) -> None:
        self._skip_stages(
            tracker,
            [
                PipelineStageName.SUMMARIZE,
                PipelineStageName.SENTIMENT,
                PipelineStageName.XAI,
                PipelineStageName.MIXED_DETECTION,
            ],
            "Skipped because the article text was not usable after cleaning/validation.",
        )

    def _skip_stages(
        self,
        tracker: PipelineStatusTracker,
        stages: list[PipelineStageName],
        message: str,
    ) -> None:
        for stage in stages:
            tracker.skip(stage, message)


def _compute_sentiment_divergence(sentiment_result: SentimentResult) -> bool | None:
    """타이틀 청크 감성이 본문 청크 지배 감성과 다를 때 True 반환."""
    from app.schemas.sentiment import SentimentChunkSource
    chunks = sentiment_result.chunk_results
    if not chunks:
        return None

    title_chunks = [c for c in chunks if c.source == SentimentChunkSource.TITLE]
    body_chunks = [c for c in chunks if c.source == SentimentChunkSource.BODY]

    if not title_chunks or not body_chunks:
        return None

    title_label = title_chunks[0].label

    label_weights: dict[str, float] = {}
    for c in body_chunks:
        label_weights[c.label.value] = label_weights.get(c.label.value, 0.0) + c.weight

    body_label = max(label_weights, key=label_weights.get)
    return title_label.value != body_label