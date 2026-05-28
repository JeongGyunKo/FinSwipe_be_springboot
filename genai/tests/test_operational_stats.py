from __future__ import annotations

from app.repositories import InMemoryEnrichmentRepository, SaveEnrichmentRequest
from app.schemas.article_fetch import (
    ArticleFetchFailureCategory,
    ArticleFetchResult,
    ArticleFetchStatus,
    ArticleTextSource,
)
from app.schemas.enrichment import ArticleEnrichmentRequest
from app.schemas.storage import (
    AnalysisOutcome,
    AnalysisStatus,
    EnrichmentStoragePayload,
    PipelineStageName,
    StoragePayloadError,
)


def test_operational_stats_aggregate_fetch_failures_and_domains() -> None:
    repository = InMemoryEnrichmentRepository()

    request_one = ArticleEnrichmentRequest(
        news_id="news-1",
        title="Title 1",
        link="https://www.reuters.com/article-1",
    )
    request_two = ArticleEnrichmentRequest(
        news_id="news-2",
        title="Title 2",
        link="https://finance.yahoo.com/article-2",
    )

    repository.upsert_raw_news(request_one)
    repository.upsert_raw_news(request_two)
    repository.create_enrichment_job("news-1")
    repository.create_enrichment_job("news-2")

    repository.save_enrichment_result(
        SaveEnrichmentRequest(
            raw_news=request_one,
            enrichment=EnrichmentStoragePayload(
                news_id="news-1",
                title="Title 1",
                link="https://www.reuters.com/article-1",
                analysis_status=AnalysisStatus.FETCH_FAILED,
                analysis_outcome=AnalysisOutcome.FATAL_FAILURE,
                fetch_result=ArticleFetchResult(
                    link="https://www.reuters.com/article-1",
                    publisher_domain="www.reuters.com",
                    final_url="https://www.reuters.com/article-1",
                    http_status_code=403,
                    content_type="text/html; charset=utf-8",
                    extraction_source=ArticleTextSource.META_DESCRIPTION,
                    attempt_count=1,
                    raw_text="",
                    cleaned_text="",
                    fetch_status=ArticleFetchStatus.FETCH_FAILED,
                    retryable=False,
                    failure_category=ArticleFetchFailureCategory.ACCESS_BLOCKED,
                    error_message="blocked",
                ),
            ),
        )
    )
    repository.save_enrichment_result(
        SaveEnrichmentRequest(
            raw_news=request_two,
            enrichment=EnrichmentStoragePayload(
                news_id="news-2",
                title="Title 2",
                link="https://finance.yahoo.com/article-2",
                analysis_status=AnalysisStatus.FETCH_FAILED,
                analysis_outcome=AnalysisOutcome.FATAL_FAILURE,
                fetch_result=ArticleFetchResult(
                    link="https://finance.yahoo.com/article-2",
                    publisher_domain="finance.yahoo.com",
                    final_url="https://finance.yahoo.com/article-2",
                    http_status_code=429,
                    content_type="text/html; charset=utf-8",
                    extraction_source=ArticleTextSource.GENERIC_JSON,
                    attempt_count=2,
                    raw_text="",
                    cleaned_text="",
                    fetch_status=ArticleFetchStatus.FETCH_FAILED,
                    retryable=True,
                    failure_category=ArticleFetchFailureCategory.RATE_LIMITED,
                    error_message="rate limited",
                ),
            ),
        )
    )
    repository.save_enrichment_result(
        SaveEnrichmentRequest(
            raw_news=ArticleEnrichmentRequest(
                news_id="news-3",
                title="Title 3",
                link="https://example.com/article-3",
            ),
            enrichment=EnrichmentStoragePayload(
                news_id="news-3",
                title="Title 3",
                link="https://example.com/article-3",
                analysis_status=AnalysisStatus.SUMMARIZE_FAILED,
                analysis_outcome=AnalysisOutcome.PARTIAL_SUCCESS,
                failure_code="summary_generation_failed",
                cleaned_text_char_count=90,
                fetch_result=ArticleFetchResult(
                    link="https://example.com/article-3",
                    publisher_domain="example.com",
                    final_url="https://example.com/article-3",
                    http_status_code=200,
                    content_type="text/html; charset=utf-8",
                    extraction_source=ArticleTextSource.PARAGRAPH_BLOCKS,
                    attempt_count=1,
                    raw_text="x" * 200,
                    cleaned_text="x" * 90,
                    fetch_status=ArticleFetchStatus.SUCCESS,
                    retryable=False,
                    failure_category=None,
                    error_message=None,
                ),
                errors=[
                    StoragePayloadError(
                        stage=PipelineStageName.SUMMARIZE,
                        message="Summary generation failed after timeout and 429 rate limit",
                        fatal=False,
                    )
                ],
            ),
        )
    )

    stats = repository.get_operational_stats()

    assert stats.total_enrichment_results == 3
    assert stats.total_jobs == 2
    assert stats.total_fetch_failures == 2
    assert stats.retryable_fetch_failures == 1
    assert stats.summarize_failed_count == 1
    assert stats.timeout_failure_count == 1
    assert stats.gemini_rate_limited_count == 1
    assert stats.average_cleaned_to_raw_ratio is not None
    assert stats.average_cleaned_to_raw_ratio > 0.0
    assert stats.low_preservation_count == 0
    assert any(item.key == "fetch_failed" and item.count == 2 for item in stats.analysis_status_counts)
    assert any(
        item.key == "generic_json" and item.count == 1 for item in stats.extraction_source_counts
    )
    assert any(item.key == "rate_limited" and item.count == 1 for item in stats.fetch_failure_category_counts)
    assert any(item.publisher_domain == "www.reuters.com" for item in stats.top_failure_domains)
    assert any(
        item.publisher_domain == "finance.yahoo.com"
        and item.fatal_failure_count == 1
        for item in stats.publisher_outcomes
    )