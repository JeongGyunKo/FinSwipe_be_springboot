import asyncio

from fastapi import HTTPException

from app.core import get_settings
from app.services.direct_enrichment_job_service import DirectEnrichmentJobService
from app.repositories import EnrichmentRepository, create_repository
from app.schemas.enrichment import (
    AlertDecision,
    AlertMode,
    ArticleEnrichmentRequest,
    ArticleEnrichmentResponse,
    DirectTextEnrichmentRequest,
    EnrichmentStatus,
    ErrorDetail,
    FlexibleTextEnrichmentRequest,
    InternalStageStatus,
    MixedConflictPayload,
    SentimentLabel,
    SentimentResult,
    StageName,
    StageIOMetric,
    StageStatus,
    SummaryLine,
    XAIDisplayEvidenceItem,
    XAIDisplayKeywordSpan,
    XAIDisplayPayload,
    XAIHighlightItem,
    XAIPayload,
)
from app.schemas.mixed import ArticleMixedDetectionResult
from app.schemas.storage import AnalysisOutcome, AnalysisStatus, EnrichmentStoragePayload
from app.schemas.xai import XAIContributionDirection, XAIResult
from app.services.orchestrator import EnrichmentOrchestrator
from app.services.response_state import map_analysis_status_to_error_code

settings = get_settings()


class EnrichmentService:
    def __init__(
        self,
        repository: EnrichmentRepository | None = None,
    ) -> None:
        self._repository = repository
        self._direct_enrichment_job_service: DirectEnrichmentJobService | None = None
        self._orchestrator: EnrichmentOrchestrator | None = (
            EnrichmentOrchestrator(repository=repository) if repository is not None else None
        )

    @property
    def repository(self) -> EnrichmentRepository:
        if self._repository is None:
            self._repository = create_repository()
        return self._repository

    @property
    def orchestrator(self) -> EnrichmentOrchestrator:
        if self._orchestrator is None:
            self._orchestrator = EnrichmentOrchestrator(repository=self.repository)
        return self._orchestrator

    @property
    def direct_enrichment_job_service(self) -> DirectEnrichmentJobService:
        if self._direct_enrichment_job_service is None:
            self._direct_enrichment_job_service = DirectEnrichmentJobService(
                repository=self.repository,
                wait_timeout_seconds=settings.direct_enrichment_wait_timeout_seconds,
                poll_interval_seconds=settings.direct_enrichment_poll_interval_seconds,
            )
        return self._direct_enrichment_job_service

    async def enrich_article(
        self,
        payload: FlexibleTextEnrichmentRequest,
    ) -> ArticleEnrichmentResponse:
        existing = await self._get_reusable_completed_result(payload)
        if existing is not None:
            return build_api_enrichment_response(existing)

        if settings.use_worker_backed_direct_enrichment:
            storage_payload = await self.direct_enrichment_job_service.submit_and_wait(payload)
            return build_api_enrichment_response(storage_payload)
        if payload.has_direct_text:
            storage_payload = await self._run_orchestrator_with_timeout(
                self.orchestrator.run_with_text,
                payload,
                article_text=payload.article_text,
                summary_text=payload.summary_text,
            )
        else:
            storage_payload = await self._run_orchestrator_with_timeout(
                self.orchestrator.run,
                payload,
            )
        return build_api_enrichment_response(storage_payload)

    async def enrich_article_text(
        self,
        payload: DirectTextEnrichmentRequest,
    ) -> ArticleEnrichmentResponse:
        existing = await self._get_reusable_completed_result(payload)
        if existing is not None:
            return build_api_enrichment_response(existing)

        if settings.use_worker_backed_direct_enrichment:
            storage_payload = await self.direct_enrichment_job_service.submit_and_wait(payload)
            return build_api_enrichment_response(storage_payload)
        storage_payload = await self._run_orchestrator_with_timeout(
            self.orchestrator.run_with_text,
            payload,
            article_text=payload.article_text,
            summary_text=payload.summary_text,
        )
        return build_api_enrichment_response(storage_payload)

    async def _run_orchestrator_with_timeout(self, callable_obj, *args, **kwargs):
        timeout_seconds = max(0.1, settings.pipeline_timeout_seconds)
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(callable_obj, *args, **kwargs),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise HTTPException(
                status_code=504,
                detail=(
                    "Enrichment pipeline timed out before completion. "
                    "Try reducing article size or retrying via worker-backed mode."
                ),
            ) from exc

    async def _get_reusable_completed_result(
        self,
        payload: FlexibleTextEnrichmentRequest,
    ) -> EnrichmentStoragePayload | None:
        existing = await asyncio.to_thread(self.repository.get_enrichment_result, payload.news_id)
        if existing is None:
            return None
        if existing.analysis_outcome != AnalysisOutcome.SUCCESS:
            return None
        if existing.analysis_status != AnalysisStatus.COMPLETED:
            return None
        if _normalize_link(existing.link) != _normalize_link(payload.link):
            return None
        return existing


def build_api_enrichment_response(
    payload: EnrichmentStoragePayload,
) -> ArticleEnrichmentResponse:
    mixed_result = payload.article_mixed
    api_sentiment = _build_sentiment_payload(payload, mixed_result)
    summary_lines = [
        SummaryLine(line_number=index, text=text)
        for index, text in enumerate(payload.summary_3lines, start=1)
    ]
    xai_payload = _build_xai_payload(payload.xai, api_sentiment)
    xai_display_payload = _build_xai_display_payload(payload.xai, api_sentiment)
    # Do not re-translate at response time. Reuse stored localized payload only.
    localized = payload.localized

    return ArticleEnrichmentResponse(
        news_id=payload.news_id,
        title=payload.title,
        link=payload.link,
        summary_3lines=summary_lines,
        sentiment=api_sentiment,
        xai=xai_payload,
        xai_display=xai_display_payload,
        localized=localized,
        headline_ko=localized.title if localized is not None else None,
        content_ko=localized.content if localized is not None else None,
        summary_3lines_ko=(
            [line.text for line in localized.summary_3lines]
            if localized is not None
            else []
        ),
        xai_ko=localized.xai if localized is not None else None,
        sentiment_reason=payload.sentiment_reason,
        mixed_flags=_build_mixed_flags(mixed_result),
        status=_map_overall_status(payload.analysis_status, payload.analysis_outcome),
        outcome=payload.analysis_outcome.value,
        pipeline_trace_id=payload.pipeline_trace_id,
        failure_code=payload.failure_code,
        analyzed_at=payload.analyzed_at,
        cleaned_text_char_count=payload.cleaned_text_char_count,
        cleaned_text_preview=payload.cleaned_text_preview,
        error=_build_error_detail(payload),
        stage_statuses=[_map_stage_status(stage) for stage in payload.stage_statuses],
        stage_io_metrics=[_map_stage_io_metric(item) for item in payload.stage_io_metrics],
        alert_decision=_build_alert_decision(api_sentiment),
        news_power_score=_build_news_power_score(api_sentiment),
    )


def _normalize_link(value: object) -> str:
    return str(value).strip().rstrip("/")


def _build_sentiment_payload(
    payload: EnrichmentStoragePayload,
    mixed_result: ArticleMixedDetectionResult | None,
) -> SentimentResult | None:
    if payload.sentiment is None:
        return None

    label = _map_sentiment_label(
        payload.sentiment.label,
        is_mixed=bool(mixed_result and mixed_result.is_mixed),
    )
    normalized_score = max(-1.0, min(1.0, round(payload.sentiment.score / 100.0, 4)))

    return SentimentResult(
        label=label,
        score=normalized_score,
        confidence=payload.sentiment.confidence,
    )


def _build_xai_payload(
    payload: XAIResult | None,
    sentiment: SentimentResult | None,
) -> XAIPayload | None:
    if payload is None:
        return None

    target_label = sentiment.label if sentiment is not None else None
    explanation = "Top article snippets influencing the sentiment result."
    if target_label is not None:
        explanation = (
            f"Top article snippets influencing the {target_label.value} sentiment result."
        )

    return XAIPayload(
        explanation=explanation,
        highlights=[
            XAIHighlightItem(
                excerpt=highlight.text_snippet,
                relevance_score=min(1.0, max(0.0, highlight.importance_score)),
                explanation=None,
                sentiment_signal=_map_highlight_signal(
                    highlight.contribution_direction,
                    target_label,
                ),
                start_char=highlight.start_char,
                end_char=highlight.end_char,
            )
            for highlight in payload.highlights
        ],
    )


def _build_xai_display_payload(
    payload: XAIResult | None,
    sentiment: SentimentResult | None,
) -> XAIDisplayPayload | None:
    if payload is None or not payload.highlights:
        return None

    target_label = sentiment.label if sentiment is not None else None
    return XAIDisplayPayload(
        evidence=[
            XAIDisplayEvidenceItem(
                excerpt=highlight.text_snippet,
                keywords=_build_xai_display_keywords(highlight),
                keyword_spans=_build_xai_display_keyword_spans(highlight),
                sentiment_signal=_map_highlight_signal(
                    highlight.contribution_direction,
                    target_label,
                ),
                relevance_score=min(1.0, max(0.0, highlight.importance_score)),
            )
            for highlight in payload.highlights
        ],
    )


def _build_xai_display_keywords(highlight) -> list[str]:
    return [
        keyword.text_snippet
        for keyword in highlight.keyword_spans
        if keyword.text_snippet.strip()
    ][:3]


def _build_xai_display_keyword_spans(highlight) -> list[XAIDisplayKeywordSpan]:
    spans: list[XAIDisplayKeywordSpan] = []
    sentence_start = highlight.start_char
    for keyword in highlight.keyword_spans[:3]:
        text = keyword.text_snippet.strip()
        if not text:
            continue

        relative_start: int | None = None
        relative_end: int | None = None
        if sentence_start is not None:
            relative_start = keyword.start_char - sentence_start
            relative_end = keyword.end_char - sentence_start
            if relative_start < 0 or relative_end < relative_start or relative_end > len(highlight.text_snippet):
                relative_start = None
                relative_end = None

        if relative_start is None:
            local_index = highlight.text_snippet.find(text)
            if local_index >= 0:
                relative_start = local_index
                relative_end = local_index + len(text)

        spans.append(
            XAIDisplayKeywordSpan(
                text=text,
                start_char=relative_start,
                end_char=relative_end,
                importance_score=keyword.importance_score,
            )
        )
    return spans


def _build_mixed_flags(
    payload: ArticleMixedDetectionResult | None,
) -> MixedConflictPayload | None:
    if payload is None:
        return None

    return MixedConflictPayload(
        is_mixed=payload.is_mixed,
        has_conflicting_signals=payload.has_conflicting_signals,
        dominant_sentiment=_map_sentiment_label(
            payload.dominant_sentiment.value if payload.dominant_sentiment is not None else None,
            is_mixed=payload.is_mixed,
        ),
        conflict_reasons=[reason.message for reason in payload.reasons if reason.triggered],
    )


def _build_error_detail(
    payload: EnrichmentStoragePayload,
) -> ErrorDetail | None:
    if payload.analysis_outcome == AnalysisOutcome.FILTERED:
        return None
    if not payload.errors:
        return None

    first_error = payload.errors[0]
    retryable = False
    if payload.fetch_result is not None and payload.analysis_status == AnalysisStatus.FETCH_FAILED:
        retryable = payload.fetch_result.retryable

    return ErrorDetail(
        code=(
            map_analysis_status_to_error_code(
                payload.analysis_status,
                retryable=retryable,
            )
            or payload.analysis_status.value
        ),
        message=first_error.message,
        retryable=retryable,
        details={
            "stage": first_error.stage.value,
            "analysis_status": payload.analysis_status.value,
            "analysis_outcome": payload.analysis_outcome.value,
        },
    )


def _map_stage_status(stage: object) -> InternalStageStatus:
    stage_name_map = {
        "fetch": StageName.FETCH,
        "clean": StageName.CLEAN,
        "validate": StageName.VALIDATE,
        "summarize": StageName.SUMMARY_GENERATION,
        "sentiment": StageName.SENTIMENT_ANALYSIS,
        "xai": StageName.XAI_EXTRACTION,
        "mixed_detection": StageName.MIXED_SIGNAL_DETECTION,
        "build_payload": StageName.BUILD_PAYLOAD,
        "persist": StageName.PERSIST,
    }
    stage_status_map = {
        "pending": StageStatus.NOT_STARTED,
        "completed": StageStatus.COMPLETED,
        "failed": StageStatus.FAILED,
        "filtered": StageStatus.FILTERED,
        "skipped": StageStatus.SKIPPED,
    }

    stage_value = getattr(stage, "stage").value
    status_value = getattr(stage, "status").value

    return InternalStageStatus(
        stage=stage_name_map[stage_value],
        status=stage_status_map[status_value],
        started_at=getattr(stage, "started_at"),
        completed_at=getattr(stage, "completed_at"),
        error=None,
    )


def _map_stage_io_metric(item: object) -> StageIOMetric:
    stage_name_map = {
        "fetch": StageName.FETCH,
        "clean": StageName.CLEAN,
        "validate": StageName.VALIDATE,
        "summarize": StageName.SUMMARY_GENERATION,
        "sentiment": StageName.SENTIMENT_ANALYSIS,
        "xai": StageName.XAI_EXTRACTION,
        "mixed_detection": StageName.MIXED_SIGNAL_DETECTION,
        "build_payload": StageName.BUILD_PAYLOAD,
        "persist": StageName.PERSIST,
    }
    stage_value = getattr(item, "stage").value
    return StageIOMetric(
        stage=stage_name_map[stage_value],
        input_chars=getattr(item, "input_chars", None),
        output_chars=getattr(item, "output_chars", None),
        output_items=getattr(item, "output_items", None),
        note=getattr(item, "note", None),
    )


def _map_overall_status(
    analysis_status: AnalysisStatus,
    analysis_outcome: AnalysisOutcome,
) -> EnrichmentStatus:
    if analysis_status == AnalysisStatus.PENDING:
        return EnrichmentStatus.PENDING
    if analysis_outcome == AnalysisOutcome.SUCCESS:
        return EnrichmentStatus.COMPLETED
    if analysis_outcome == AnalysisOutcome.PARTIAL_SUCCESS:
        return EnrichmentStatus.PARTIAL
    if analysis_outcome == AnalysisOutcome.FILTERED:
        return EnrichmentStatus.FILTERED
    return EnrichmentStatus.FAILED


def _map_sentiment_label(
    label: str | None,
    *,
    is_mixed: bool,
) -> SentimentLabel | None:
    if label is None:
        return None
    if is_mixed:
        return SentimentLabel.MIXED
    label_map = {
        "positive": SentimentLabel.BULLISH,
        "negative": SentimentLabel.BEARISH,
        "neutral": SentimentLabel.NEUTRAL,
    }
    return label_map.get(label, SentimentLabel.NEUTRAL)


def _map_highlight_signal(
    direction: XAIContributionDirection,
    target_label: SentimentLabel | None,
) -> SentimentLabel | None:
    if target_label is None:
        return None
    if direction == XAIContributionDirection.POSITIVE:
        return target_label
    opposite_map = {
        SentimentLabel.BULLISH: SentimentLabel.BEARISH,
        SentimentLabel.BEARISH: SentimentLabel.BULLISH,
        SentimentLabel.NEUTRAL: SentimentLabel.NEUTRAL,
        SentimentLabel.MIXED: SentimentLabel.MIXED,
    }
    return opposite_map[target_label]


def _build_alert_decision(sentiment: SentimentResult | None) -> AlertDecision:
    if not settings.alerts_enabled:
        return AlertDecision(
            should_send=False,
            mode=AlertMode.ALL,
            reason_code="alerts_disabled",
            reason="All alerts are disabled by runtime policy.",
        )

    if not settings.sentiment_only_alerts:
        return AlertDecision(
            should_send=True,
            mode=AlertMode.ALL,
            reason_code="all_alerts_enabled",
            reason="All article alerts are enabled regardless of sentiment.",
        )

    if sentiment is None:
        return AlertDecision(
            should_send=False,
            mode=AlertMode.SENTIMENT_ONLY,
            reason_code="sentiment_missing",
            reason="Sentiment-only alert mode requires a sentiment result.",
        )

    if sentiment.confidence < settings.sentiment_alert_min_confidence:
        return AlertDecision(
            should_send=False,
            mode=AlertMode.SENTIMENT_ONLY,
            reason_code="sentiment_confidence_low",
            reason=(
                "Sentiment confidence is below the minimum threshold "
                f"({settings.sentiment_alert_min_confidence:.2f})."
            ),
        )

    if sentiment.label in {SentimentLabel.BULLISH, SentimentLabel.BEARISH}:
        return AlertDecision(
            should_send=True,
            mode=AlertMode.SENTIMENT_ONLY,
            reason_code="sentiment_label_allowed",
            reason="Sentiment-only alert mode allows bullish/bearish articles.",
        )

    if sentiment.label == SentimentLabel.NEUTRAL:
        return AlertDecision(
            should_send=False,
            mode=AlertMode.SENTIMENT_ONLY,
            reason_code="sentiment_neutral_filtered",
            reason="Neutral sentiment is excluded in sentiment-only alert mode.",
        )

    return AlertDecision(
        should_send=False,
        mode=AlertMode.SENTIMENT_ONLY,
        reason_code="sentiment_mixed_filtered",
        reason="Mixed sentiment is excluded in sentiment-only alert mode.",
    )


def _build_news_power_score(sentiment: SentimentResult | None) -> float | None:
    if sentiment is None:
        return None
    return round(abs(sentiment.score) * sentiment.confidence, 4)