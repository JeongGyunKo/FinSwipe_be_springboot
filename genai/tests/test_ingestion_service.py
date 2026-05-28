from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.repositories import InMemoryEnrichmentRepository
from app.schemas.article_fetch import ArticleFetchResult, ArticleFetchStatus
from app.schemas.enrichment import ArticleEnrichmentRequest
from app.schemas.storage import AnalysisOutcome, AnalysisStatus, EnrichmentStoragePayload
from app.services.article_fetcher import FetchRetryPolicy
from app.services.job_processing_service import JobProcessingService


def _build_fatal_payload(*, retryable: bool) -> EnrichmentStoragePayload:
    return EnrichmentStoragePayload(
        news_id="news-1",
        title="Test title",
        link="https://example.com/article",
        summary_3lines=[],
        sentiment=None,
        xai=None,
        article_mixed=None,
        ticker_mixed=None,
        analysis_status=AnalysisStatus.FETCH_FAILED,
        analysis_outcome=AnalysisOutcome.FATAL_FAILURE,
        cleaned_text_available=False,
        fetch_result=ArticleFetchResult(
            link="https://example.com/article",
            raw_text="",
            cleaned_text="",
            fetch_status=ArticleFetchStatus.FETCH_FAILED,
            retryable=retryable,
            error_message="temporary failure" if retryable else "403 forbidden",
        ),
    )


def test_process_next_job_requeues_retryable_fetch_failure(monkeypatch) -> None:
    repository = InMemoryEnrichmentRepository()
    service = JobProcessingService(
        repository=repository,
        fetch_retry_policy=FetchRetryPolicy(base_backoff_seconds=2.0, max_backoff_seconds=2.0),
    )
    request = ArticleEnrichmentRequest(
        news_id="news-1",
        title="Title",
        link="https://example.com/article",
    )
    repository.upsert_raw_news(request)
    repository.create_enrichment_job("news-1", max_attempts=3)

    monkeypatch.setattr(
        service.orchestrator,
        "run",
        lambda raw_news: _build_fatal_payload(retryable=True),
    )

    result = service.process_next_job()

    assert result.retry_scheduled is True
    assert result.job is not None
    assert result.job.status.value == "retry_pending"
    assert result.processing_state.value == "retry_pending"
    assert result.error_code == "article_fetch_retryable"
    assert result.job.next_retry_at is not None
    assert result.job.next_retry_at > datetime.now(timezone.utc)


def test_process_next_job_fails_non_retryable_fetch_failure(monkeypatch) -> None:
    repository = InMemoryEnrichmentRepository()
    service = JobProcessingService(repository=repository)
    request = ArticleEnrichmentRequest(
        news_id="news-1",
        title="Title",
        link="https://example.com/article",
    )
    repository.upsert_raw_news(request)
    repository.create_enrichment_job("news-1", max_attempts=3)

    monkeypatch.setattr(
        service.orchestrator,
        "run",
        lambda raw_news: _build_fatal_payload(retryable=False),
    )

    result = service.process_next_job()

    assert result.retry_scheduled is False
    assert result.job is not None
    assert result.job.status.value == "failed"
    assert result.processing_state.value == "failed"
    assert result.error_code == "article_fetch_failed"


def test_claim_next_job_skips_retry_pending_until_due() -> None:
    repository = InMemoryEnrichmentRepository()
    request = ArticleEnrichmentRequest(
        news_id="news-1",
        title="Title",
        link="https://example.com/article",
    )
    repository.upsert_raw_news(request)
    repository.create_enrichment_job("news-1", max_attempts=3)

    claimed = repository.claim_next_enrichment_job()
    assert claimed is not None

    repository.requeue_job(
        claimed.job_id,
        error_message="retry later",
        next_retry_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        analysis_status=AnalysisStatus.FETCH_FAILED,
    )

    assert repository.claim_next_enrichment_job() is None


def test_claim_next_job_picks_retry_pending_when_due() -> None:
    repository = InMemoryEnrichmentRepository()
    request = ArticleEnrichmentRequest(
        news_id="news-1",
        title="Title",
        link="https://example.com/article",
    )
    repository.upsert_raw_news(request)
    repository.create_enrichment_job("news-1", max_attempts=3)

    claimed = repository.claim_next_enrichment_job()
    assert claimed is not None

    repository.requeue_job(
        claimed.job_id,
        error_message="retry now",
        next_retry_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        analysis_status=AnalysisStatus.FETCH_FAILED,
    )

    next_claim = repository.claim_next_enrichment_job()
    assert next_claim is not None
    assert next_claim.status.value == "processing"


def test_process_next_job_marks_filtered_result_completed(monkeypatch) -> None:
    repository = InMemoryEnrichmentRepository()
    service = JobProcessingService(repository=repository)
    request = ArticleEnrichmentRequest(
        news_id="news-filtered",
        title="Transcript page",
        link="https://example.com/transcript",
    )
    repository.upsert_raw_news(request)
    repository.create_enrichment_job("news-filtered", max_attempts=3)

    monkeypatch.setattr(
        service.orchestrator,
        "run",
        lambda raw_news: EnrichmentStoragePayload(
            news_id="news-filtered",
            title="Transcript page",
            link="https://example.com/transcript",
            analysis_status=AnalysisStatus.CLEAN_FILTERED,
            analysis_outcome=AnalysisOutcome.FILTERED,
            cleaned_text_available=False,
            fetch_result=ArticleFetchResult(
                link="https://example.com/transcript",
                raw_text="",
                cleaned_text="",
                fetch_status=ArticleFetchStatus.SUCCESS,
                retryable=False,
                error_message=None,
            ),
            stage_statuses=[],
            errors=[],
        ),
    )

    result = service.process_next_job()

    assert result.retry_scheduled is False
    assert result.job is not None
    assert result.job.status.value == "completed"
    assert result.processing_state.value == "completed"
    assert result.error_code is None
    assert result.analysis_status == AnalysisStatus.CLEAN_FILTERED
    assert result.analysis_outcome == AnalysisOutcome.FILTERED