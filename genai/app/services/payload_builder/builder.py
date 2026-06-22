from __future__ import annotations

from datetime import datetime, timezone
import logging

from app.core.logging import log_event
from app.schemas.article_fetch import ArticleFetchResult
from app.schemas.enrichment import (
    ErrorCode,
    LocalizedArticleContent,
    SentimentLabel,
    SummaryLine,
    XAIHighlightItem,
    XAIPayload,
)
from app.schemas.mixed import (
    ArticleMixedDetectionResult,
    TickerMixedDetectionResult,
)
from app.schemas.sentiment import SentimentResult as FinBERTSentimentResult
from app.schemas.storage import (
    AnalysisOutcome,
    AnalysisStatus,
    EnrichmentStoragePayload,
    StageIOMetric,
    PipelineStageName,
    PipelineStageResult,
    StoragePayloadError,
    build_stored_sentiment_payload,
)
from app.schemas.xai import XAIContributionDirection
from app.schemas.xai import XAIResult
from app.core import get_settings
from app.services.translation import build_localized_content

logger = logging.getLogger(__name__)

_SENTIMENT_LABELS_KO: dict[SentimentLabel, str] = {
    SentimentLabel.BULLISH: "강세",
    SentimentLabel.BEARISH: "약세",
    SentimentLabel.NEUTRAL: "중립",
    SentimentLabel.MIXED: "혼합",
}


def build_enrichment_storage_payload(
    *,
    news_id: str,
    title: str,
    link: str,
    analysis_status: AnalysisStatus,
    analysis_outcome: AnalysisOutcome,
    pipeline_trace_id: str | None = None,
    stage_statuses: list[PipelineStageResult],
    fetch_result: ArticleFetchResult | None = None,
    cleaned_text: str | None = None,
    summary_3lines: list[str] | None = None,
    sentiment_result: FinBERTSentimentResult | None = None,
    xai_result: XAIResult | None = None,
    sentiment_reason: str | None = None,
    event_category: str | None = None,
    sentiment_divergence: bool | None = None,
    article_mixed: ArticleMixedDetectionResult | None = None,
    ticker_mixed: TickerMixedDetectionResult | None = None,
    tickers: list[str] | None = None,
    analyzed_at: datetime | None = None,
    errors: list[StoragePayloadError] | None = None,
    prebuilt_headline_ko: str | None = None,
) -> EnrichmentStoragePayload:
    """Assemble a database-ready storage payload from enrichment stage outputs."""
    cleaned_text_normalized = (cleaned_text or "").strip()
    normalized_summary = _normalize_summary_lines(summary_3lines)
    stored_sentiment = (
        build_stored_sentiment_payload(sentiment_result)
        if sentiment_result is not None
        else None
    )
    localized = _build_stored_localized_content(
        title=title,
        content_text=_build_localized_content_excerpt(cleaned_text_normalized),
        summary_3lines=normalized_summary,
        sentiment_label=stored_sentiment.label if stored_sentiment is not None else None,
        xai_result=xai_result,
        is_mixed=bool(article_mixed and article_mixed.is_mixed),
        tickers=tickers,
        analysis_outcome=analysis_outcome,
        prebuilt_headline_ko=prebuilt_headline_ko,
    )

    aggregated_errors = list(errors or [])
    _append_payload_warnings(
        errors=aggregated_errors,
        analysis_outcome=analysis_outcome,
        normalized_summary=normalized_summary,
        cleaned_text_available=bool(cleaned_text_normalized),
        localized=localized,
        sentiment_available=stored_sentiment is not None,
    )
    _log_localization_status(
        news_id=news_id,
        analysis_outcome=analysis_outcome,
        summary_line_count=len(normalized_summary),
        localized=localized,
    )

    return EnrichmentStoragePayload(
        news_id=news_id,
        title=title,
        link=link,
        summary_3lines=normalized_summary,
        sentiment=stored_sentiment,
        xai=xai_result,
        sentiment_reason=sentiment_reason,
        event_category=event_category,
        sentiment_divergence=sentiment_divergence,
        localized=localized,
        article_mixed=article_mixed,
        ticker_mixed=ticker_mixed,
        analysis_status=analysis_status,
        analysis_outcome=analysis_outcome,
        pipeline_trace_id=pipeline_trace_id,
        failure_code=_derive_failure_code(
            analysis_status=analysis_status,
            analysis_outcome=analysis_outcome,
            errors=aggregated_errors,
            fetch_result=fetch_result,
        ),
        analyzed_at=_normalize_timestamp(analyzed_at),
        cleaned_text_char_count=len(cleaned_text_normalized),
        cleaned_text_preview=_build_cleaned_text_preview(cleaned_text_normalized),
        cleaned_text_available=bool(cleaned_text_normalized),
        fetch_result=fetch_result,
        stage_statuses=stage_statuses,
        stage_io_metrics=_build_stage_io_metrics(
            fetch_result=fetch_result,
            cleaned_text=cleaned_text_normalized,
            normalized_summary=normalized_summary,
            sentiment_available=stored_sentiment is not None,
            xai_result=xai_result,
            localized=localized,
        ),
        errors=aggregated_errors,
    )


def _derive_failure_code(
    *,
    analysis_status: AnalysisStatus,
    analysis_outcome: AnalysisOutcome,
    errors: list[StoragePayloadError],
    fetch_result: ArticleFetchResult | None,
) -> str | None:
    if analysis_outcome == AnalysisOutcome.SUCCESS:
        return None

    if analysis_status == AnalysisStatus.FETCH_FAILED:
        if fetch_result is not None and fetch_result.retryable:
            return ErrorCode.ARTICLE_FETCH_RETRYABLE.value
        return ErrorCode.ARTICLE_FETCH_FAILED.value

    status_mapping: dict[AnalysisStatus, ErrorCode] = {
        AnalysisStatus.CLEAN_FAILED: ErrorCode.TEXT_CLEAN_FAILED,
        AnalysisStatus.VALIDATE_FAILED: ErrorCode.ARTICLE_TEXT_INVALID,
        AnalysisStatus.SUMMARIZE_FAILED: ErrorCode.SUMMARY_GENERATION_FAILED,
        AnalysisStatus.SENTIMENT_FAILED: ErrorCode.SENTIMENT_ANALYSIS_FAILED,
        AnalysisStatus.XAI_FAILED: ErrorCode.XAI_EXTRACTION_FAILED,
        AnalysisStatus.MIXED_DETECTION_FAILED: ErrorCode.MIXED_SIGNAL_DETECTION_FAILED,
        AnalysisStatus.BUILD_PAYLOAD_FAILED: ErrorCode.PAYLOAD_BUILD_FAILED,
        AnalysisStatus.PERSIST_FAILED: ErrorCode.RESULT_PERSIST_FAILED,
    }
    mapped = status_mapping.get(analysis_status)
    if mapped is not None:
        return mapped.value

    if errors:
        stage_mapping: dict[PipelineStageName, ErrorCode] = {
            PipelineStageName.FETCH: ErrorCode.ARTICLE_FETCH_FAILED,
            PipelineStageName.CLEAN: ErrorCode.TEXT_CLEAN_FAILED,
            PipelineStageName.VALIDATE: ErrorCode.ARTICLE_TEXT_INVALID,
            PipelineStageName.SUMMARIZE: ErrorCode.SUMMARY_GENERATION_FAILED,
            PipelineStageName.SENTIMENT: ErrorCode.SENTIMENT_ANALYSIS_FAILED,
            PipelineStageName.XAI: ErrorCode.XAI_EXTRACTION_FAILED,
            PipelineStageName.MIXED_DETECTION: ErrorCode.MIXED_SIGNAL_DETECTION_FAILED,
            PipelineStageName.BUILD_PAYLOAD: ErrorCode.PAYLOAD_BUILD_FAILED,
            PipelineStageName.PERSIST: ErrorCode.RESULT_PERSIST_FAILED,
        }
        mapped_from_stage = stage_mapping.get(errors[0].stage)
        if mapped_from_stage is not None:
            return mapped_from_stage.value

    if analysis_outcome in {AnalysisOutcome.PARTIAL_SUCCESS, AnalysisOutcome.FATAL_FAILURE}:
        return ErrorCode.UNKNOWN_FAILURE.value
    return None


def _normalize_summary_lines(summary_3lines: list[str] | None) -> list[str]:
    if not summary_3lines:
        return []
    return [line.strip() for line in summary_3lines if line and line.strip()][:3]


def _build_cleaned_text_preview(cleaned_text: str) -> str | None:
    if not cleaned_text:
        return None
    preview_limit = 1200
    return cleaned_text[:preview_limit]


def _build_localized_content_excerpt(cleaned_text: str) -> str | None:
    if not cleaned_text:
        return None

    limit = max(0, get_settings().localized_content_char_limit)
    if limit <= 0:
        return None

    normalized = " ".join(cleaned_text.split())
    if len(normalized) <= limit:
        return normalized

    excerpt = normalized[:limit].rsplit(" ", 1)[0].rstrip(",;:-")
    return excerpt or normalized[:limit]


_TICKER_BOX_LABELS_KO = {
    "revenue": "매출", "net_income": "순이익", "operating_income": "영업이익",
    "guidance": "가이던스", "target_price": "목표주가", "dividend": "배당",
    "eps": "EPS", "yoy": "YoY", "qoq": "QoQ", "market_cap": "시가총액", "pe_ratio": "PER",
}


def _build_stored_localized_content(
    *,
    title: str,
    content_text: str | None,
    summary_3lines: list[str],
    sentiment_label: str | None,
    xai_result: XAIResult | None,
    is_mixed: bool,
    tickers: list[str] | None,
    analysis_outcome: AnalysisOutcome,
    prebuilt_headline_ko: str | None = None,
) -> LocalizedArticleContent | None:
    if analysis_outcome == AnalysisOutcome.FILTERED:
        return None

    localized_sentiment = _map_sentiment_label(sentiment_label, is_mixed=is_mixed)

    # 통합 분석 결과가 있으면 Gemini 번역 호출 없이 바로 생성
    if prebuilt_headline_ko:
        localized_summary = [
            SummaryLine(line_number=i + 1, text=line)
            for i, line in enumerate(summary_3lines)
        ] if summary_3lines else []
        return LocalizedArticleContent(
            language="ko",
            title=prebuilt_headline_ko,
            content=None,
            summary_3lines=localized_summary,
            xai=None,
            sentiment_label=_SENTIMENT_LABELS_KO.get(localized_sentiment),
            ticker_box_labels=dict(_TICKER_BOX_LABELS_KO),
        )

    return build_localized_content(
        title=title,
        content_text=content_text,
        summary_3lines=[],
        xai=_build_localized_xai_payload(xai_result, localized_sentiment),
        sentiment_label=localized_sentiment,
        tickers=tickers,
        xai_highlight_limit=get_settings().localized_xai_highlight_limit,
        allow_gemini=True,
    )


def _build_localized_xai_payload(
    payload: XAIResult | None,
    sentiment_label: SentimentLabel | None,
) -> XAIPayload | None:
    if payload is None:
        return None

    explanation = "Top article snippets influencing the sentiment result."
    if sentiment_label is not None:
        explanation = f"Top article snippets influencing the {sentiment_label.value} sentiment result."

    return XAIPayload(
        explanation=explanation,
        highlights=[
            XAIHighlightItem(
                excerpt=highlight.text_snippet,
                relevance_score=min(1.0, max(0.0, highlight.importance_score)),
                explanation=None,
                sentiment_signal=_map_highlight_signal(
                    highlight.contribution_direction,
                    sentiment_label,
                ),
                start_char=highlight.start_char,
                end_char=highlight.end_char,
            )
            for highlight in payload.highlights
        ],
    )


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
    if direction == XAIContributionDirection.POSITIVE:
        return SentimentLabel.BULLISH
    if direction == XAIContributionDirection.NEGATIVE:
        return SentimentLabel.BEARISH
    return target_label


def _normalize_timestamp(value: datetime | None) -> datetime:
    timestamp = value or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def _append_payload_warnings(
    *,
    errors: list[StoragePayloadError],
    analysis_outcome: AnalysisOutcome,
    normalized_summary: list[str],
    cleaned_text_available: bool,
    localized: LocalizedArticleContent | None,
    sentiment_available: bool,
) -> None:
    if analysis_outcome == AnalysisOutcome.FILTERED:
        return

    if localized is None:
        errors.append(
            StoragePayloadError(
                stage=PipelineStageName.BUILD_PAYLOAD,
                message="Localized Korean payload is empty.",
                fatal=False,
            )
        )
    if localized is not None and cleaned_text_available and not (localized.content or "").strip():
        errors.append(
            StoragePayloadError(
                stage=PipelineStageName.BUILD_PAYLOAD,
                message="Localized payload has no translated article content.",
                fatal=False,
            )
        )
    if not sentiment_available:
        errors.append(
            StoragePayloadError(
                stage=PipelineStageName.SENTIMENT,
                message="Sentiment result is missing.",
                fatal=False,
            )
        )


def _log_localization_status(
    *,
    news_id: str,
    analysis_outcome: AnalysisOutcome,
    summary_line_count: int,
    localized: LocalizedArticleContent | None,
) -> None:
    log_event(
        logger,
        logging.INFO,
        "payload_localization_status",
        news_id=news_id,
        analysis_outcome=analysis_outcome.value,
        summary_line_count=summary_line_count,
        localized_present=localized is not None,
        localized_content_available=(
            bool((localized.content or "").strip()) if localized is not None else False
        ),
        localized_summary_line_count=(
            len(localized.summary_3lines) if localized is not None else 0
        ),
    )


def _build_stage_io_metrics(
    *,
    fetch_result: ArticleFetchResult | None,
    cleaned_text: str,
    normalized_summary: list[str],
    sentiment_available: bool,
    xai_result: XAIResult | None,
    localized: LocalizedArticleContent | None,
) -> list[StageIOMetric]:
    fetch_input_chars = len(fetch_result.raw_text or "") if fetch_result is not None else None
    clean_input_chars = (
        len((fetch_result.raw_text or fetch_result.cleaned_text or ""))
        if fetch_result is not None
        else None
    )
    summary_chars = sum(len(line) for line in normalized_summary)

    metrics: list[StageIOMetric] = [
        StageIOMetric(
            stage=PipelineStageName.FETCH,
            input_chars=fetch_input_chars,
            output_chars=fetch_input_chars,
            output_items=None,
            note="Uses provided article_text/summary_text when supplied.",
        ),
        StageIOMetric(
            stage=PipelineStageName.CLEAN,
            input_chars=clean_input_chars,
            output_chars=len(cleaned_text) if cleaned_text else 0,
            output_items=None,
            note=None,
        ),
        StageIOMetric(
            stage=PipelineStageName.VALIDATE,
            input_chars=len(cleaned_text) if cleaned_text else 0,
            output_chars=len(cleaned_text) if cleaned_text else 0,
            output_items=None,
            note=None,
        ),
        StageIOMetric(
            stage=PipelineStageName.SUMMARIZE,
            input_chars=len(cleaned_text) if cleaned_text else 0,
            output_chars=summary_chars,
            output_items=len(normalized_summary),
            note=None,
        ),
        StageIOMetric(
            stage=PipelineStageName.SENTIMENT,
            input_chars=len(cleaned_text) if cleaned_text else 0,
            output_chars=None,
            output_items=1 if sentiment_available else 0,
            note=None,
        ),
        StageIOMetric(
            stage=PipelineStageName.XAI,
            input_chars=len(cleaned_text) if cleaned_text else 0,
            output_chars=None,
            output_items=len(xai_result.highlights) if xai_result is not None else 0,
            note=None,
        ),
        StageIOMetric(
            stage=PipelineStageName.BUILD_PAYLOAD,
            input_chars=None,
            output_chars=None,
            output_items=(
                len(localized.summary_3lines) if localized is not None else 0
            ),
            note="localized.summary_3lines count",
        ),
    ]
    return metrics