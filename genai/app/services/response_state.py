from __future__ import annotations

from app.schemas.enrichment import ErrorCode
from app.schemas.ingestion import EnrichmentJobRecord, EnrichmentJobStatus, ProcessingState
from app.schemas.storage import AnalysisStatus, EnrichmentStoragePayload


def derive_processing_state(
    *,
    latest_job: EnrichmentJobRecord | None,
    enrichment: EnrichmentStoragePayload | None,
) -> ProcessingState:
    if latest_job is not None:
        return ProcessingState(latest_job.status.value)
    if enrichment is not None:
        return ProcessingState.COMPLETED
    return ProcessingState.QUEUED


def derive_error_code(
    *,
    latest_job: EnrichmentJobRecord | None,
    enrichment: EnrichmentStoragePayload | None,
) -> str | None:
    analysis_status = None
    retryable = False

    if enrichment is not None:
        analysis_status = enrichment.analysis_status
        if enrichment.fetch_result is not None:
            retryable = bool(enrichment.fetch_result.retryable)
    elif latest_job is not None:
        analysis_status = latest_job.last_analysis_status

    return map_analysis_status_to_error_code(analysis_status, retryable=retryable)


def map_job_status_to_processing_state(job_status: EnrichmentJobStatus) -> ProcessingState:
    return ProcessingState(job_status.value)


def map_analysis_status_to_error_code(
    analysis_status: AnalysisStatus | None,
    *,
    retryable: bool = False,
) -> str | None:
    if analysis_status is None or analysis_status == AnalysisStatus.PENDING:
        return None

    mapping = {
        AnalysisStatus.FETCH_FAILED: (
            ErrorCode.ARTICLE_FETCH_RETRYABLE if retryable else ErrorCode.ARTICLE_FETCH_FAILED
        ),
        AnalysisStatus.CLEAN_FAILED: ErrorCode.TEXT_CLEAN_FAILED,
        AnalysisStatus.VALIDATE_FAILED: ErrorCode.ARTICLE_TEXT_INVALID,
        AnalysisStatus.SUMMARIZE_FAILED: ErrorCode.SUMMARY_GENERATION_FAILED,
        AnalysisStatus.SENTIMENT_FAILED: ErrorCode.SENTIMENT_ANALYSIS_FAILED,
        AnalysisStatus.XAI_FAILED: ErrorCode.XAI_EXTRACTION_FAILED,
        AnalysisStatus.MIXED_DETECTION_FAILED: ErrorCode.MIXED_SIGNAL_DETECTION_FAILED,
        AnalysisStatus.BUILD_PAYLOAD_FAILED: ErrorCode.PAYLOAD_BUILD_FAILED,
        AnalysisStatus.PERSIST_FAILED: ErrorCode.RESULT_PERSIST_FAILED,
    }
    mapped = mapping.get(analysis_status)
    return mapped.value if mapped is not None else None