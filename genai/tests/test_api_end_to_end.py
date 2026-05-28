from __future__ import annotations

from datetime import datetime, timedelta, timezone
from dataclasses import replace

from fastapi.testclient import TestClient
from pydantic import ValidationError

import app.api.routes.enrichment as enrichment_route_module
import app.api.routes.ingestion as ingestion_route_module
from app.main import app
from app.repositories import InMemoryEnrichmentRepository, SaveEnrichmentRequest
from app.schemas.article_fetch import ArticleFetchResult, ArticleFetchStatus, ArticleTextSource
from app.schemas.enrichment import (
    ArticleEnrichmentRequest,
    DirectTextEnrichmentRequest,
    FlexibleTextEnrichmentRequest,
    LocalizedArticleContent,
    SummaryLine,
)
from app.schemas.ingestion import EnrichmentJobRecord, EnrichmentJobStatus
from app.schemas.sentiment import (
    AggregationStrategy,
    ChunkSentimentResult,
    FinBERTSentimentLabel,
    SentimentChunkSource,
    SentimentProbabilities,
    SentimentResult,
)
from app.schemas.storage import (
    AnalysisOutcome,
    AnalysisStatus,
    EnrichmentStoragePayload,
    build_stored_sentiment_payload,
)
from app.schemas.xai import XAIContributionDirection, XAIHighlight, XAIKeywordSpan, XAIResult
from app.services.enrichment_service import EnrichmentService
from app.services.ingestion_service import IngestionService
from app.services.job_processing_service import JobProcessingService


def _build_completed_payload(request: ArticleEnrichmentRequest) -> EnrichmentStoragePayload:
    now = datetime.now(timezone.utc)
    return EnrichmentStoragePayload(
        news_id=request.news_id,
        title=request.title,
        link=str(request.link),
        summary_3lines=[
            "Revenue growth stayed ahead of expectations.",
            "Management highlighted stable demand and improved margins.",
            "Investors are watching whether guidance remains intact.",
        ],
        sentiment=build_stored_sentiment_payload(
            SentimentResult(
                label=FinBERTSentimentLabel.POSITIVE,
                score=61.0,
                confidence=0.86,
                probabilities=SentimentProbabilities(
                    positive=0.81,
                    neutral=0.14,
                    negative=0.05,
                ),
                aggregation_strategy=AggregationStrategy.WEIGHTED_MEAN,
                chunk_results=[
                    ChunkSentimentResult(
                        chunk_index=0,
                        source=SentimentChunkSource.BODY,
                        text="Revenue growth stayed ahead of expectations.",
                        token_count=12,
                        weight=1.0,
                        label=FinBERTSentimentLabel.POSITIVE,
                        score=61.0,
                        confidence=0.86,
                        probabilities=SentimentProbabilities(
                            positive=0.81,
                            neutral=0.14,
                            negative=0.05,
                        ),
                    )
                ],
                disagreement_ratio=0.0,
                chunk_count=1,
            )
        ),
        xai=XAIResult(
            target_label=FinBERTSentimentLabel.POSITIVE,
            highlights=[
                XAIHighlight(
                    text_snippet="Revenue growth stayed ahead of expectations.",
                    weight=0.125,
                    importance_score=0.125,
                    contribution_direction=XAIContributionDirection.POSITIVE,
                    sentence_index=0,
                    start_char=0,
                    end_char=41,
                    keyword_spans=[
                        XAIKeywordSpan(
                            text_snippet="Revenue",
                            start_char=0,
                            end_char=7,
                            importance_score=0.12,
                        ),
                        XAIKeywordSpan(
                            text_snippet="expectations",
                            start_char=29,
                            end_char=41,
                            importance_score=0.10,
                        ),
                    ],
                )
            ],
            limitations=[
                "Sentence-level explanation only.",
            ],
            sentence_count=1,
            truncated=False,
        ),
        article_mixed=None,
        ticker_mixed=None,
        analysis_status=AnalysisStatus.COMPLETED,
        analysis_outcome=AnalysisOutcome.SUCCESS,
        analyzed_at=now,
        cleaned_text_available=True,
        fetch_result=ArticleFetchResult(
            link=str(request.link),
            publisher_domain="example.com",
            final_url=str(request.link),
            content_type="text/html; charset=utf-8",
            extraction_source=ArticleTextSource.PARAGRAPH_BLOCKS,
            attempt_count=1,
            raw_text="Revenue growth stayed ahead of expectations.",
            cleaned_text="Revenue growth stayed ahead of expectations.",
            fetch_status=ArticleFetchStatus.SUCCESS,
            retryable=False,
            failure_category=None,
            error_message=None,
        ),
        stage_statuses=[],
        errors=[],
    )


def _build_filtered_payload(request: ArticleEnrichmentRequest) -> EnrichmentStoragePayload:
    now = datetime.now(timezone.utc)
    return EnrichmentStoragePayload(
        news_id=request.news_id,
        title=request.title,
        link=str(request.link),
        summary_3lines=[],
        sentiment=None,
        xai=None,
        article_mixed=None,
        ticker_mixed=None,
        analysis_status=AnalysisStatus.CLEAN_FILTERED,
        analysis_outcome=AnalysisOutcome.FILTERED,
        analyzed_at=now,
        cleaned_text_available=False,
        fetch_result=ArticleFetchResult(
            link=str(request.link),
            publisher_domain="example.com",
            final_url=str(request.link),
            content_type="text/html; charset=utf-8",
            extraction_source=ArticleTextSource.PARAGRAPH_BLOCKS,
            attempt_count=1,
            raw_text="Transcript header only",
            cleaned_text="",
            fetch_status=ArticleFetchStatus.SUCCESS,
            retryable=False,
            failure_category=None,
            error_message=None,
        ),
        stage_statuses=[],
        errors=[],
    )


def _build_localized_payload() -> LocalizedArticleContent:
    return LocalizedArticleContent(
        language="ko",
        title="회사가 실적 예상치를 웃돌았다",
        content="회사는 매출 성장이 예상치를 웃돌았고 경영진은 안정적인 수요를 강조했다.",
        summary_3lines=[
            SummaryLine(line_number=1, text="매출 성장이 예상치를 웃돌았다."),
            SummaryLine(line_number=2, text="경영진은 안정적인 수요를 강조했다."),
            SummaryLine(line_number=3, text="투자자들은 가이던스 유지 여부를 주시하고 있다."),
        ],
        xai=None,
        sentiment_label="강세",
        ticker_box_labels={"revenue": "매출"},
    )


def test_news_intake_worker_and_status_flow(monkeypatch) -> None:
    repository = InMemoryEnrichmentRepository()
    service = IngestionService(repository=repository)
    job_service = JobProcessingService(repository=repository)

    def _run_and_persist(raw_news: ArticleEnrichmentRequest) -> EnrichmentStoragePayload:
        payload = _build_completed_payload(raw_news)
        repository.save_enrichment_result(
            SaveEnrichmentRequest(raw_news=raw_news, enrichment=payload)
        )
        return payload

    monkeypatch.setattr(ingestion_route_module, "service", service)
    monkeypatch.setattr(ingestion_route_module, "job_service", job_service)
    monkeypatch.setattr(job_service.orchestrator, "run", _run_and_persist)

    client = TestClient(app)

    intake_response = client.post(
        "/api/v1/news/intake",
        json={
            "news_id": "e2e-news-1",
            "title": "Company beats earnings estimates",
            "link": "https://example.com/articles/e2e-news-1",
            "ticker": ["AAPL"],
            "source": "Reuters",
        },
    )

    assert intake_response.status_code == 200
    intake_payload = intake_response.json()
    assert intake_payload["queued"] is True
    assert intake_payload["processing_state"] == "queued"
    assert intake_payload["error_code"] is None
    assert intake_payload["job"]["status"] == "queued"

    worker_response = client.post("/api/v1/jobs/process-next")

    assert worker_response.status_code == 200
    worker_payload = worker_response.json()
    assert worker_payload["processed"] is True
    assert worker_payload["retry_scheduled"] is False
    assert worker_payload["processing_state"] == "completed"
    assert worker_payload["error_code"] is None
    assert worker_payload["analysis_status"] == "completed"
    assert worker_payload["analysis_outcome"] == "success"
    assert worker_payload["job"]["status"] == "completed"
    assert worker_payload["enrichment"]["xai"]["explanation_method"] == "attention_sentence"

    status_response = client.get("/api/v1/news/e2e-news-1")
    result_response = client.get("/api/v1/news/e2e-news-1/result")

    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["raw_news"]["news_id"] == "e2e-news-1"
    assert status_payload["processing_state"] == "completed"
    assert status_payload["error_code"] is None
    assert status_payload["latest_job"]["status"] == "completed"
    assert status_payload["enrichment"]["analysis_status"] == "completed"
    assert len(status_payload["enrichment"]["summary_3lines"]) == 3
    assert status_payload["enrichment"]["sentiment"]["label"] == "positive"
    assert (
        status_payload["enrichment"]["fetch_result"]["extraction_source"]
        == "paragraph_blocks"
    )
    assert status_payload["enrichment"]["xai"]["highlights"][0]["start_char"] == 0
    assert status_payload["enrichment"]["xai"]["highlights"][0]["end_char"] == 41
    assert "keyword_spans" in status_payload["enrichment"]["xai"]["highlights"][0]

    assert result_response.status_code == 200
    result_payload = result_response.json()
    assert result_payload["raw_news"]["news_id"] == "e2e-news-1"
    assert result_payload["processing_state"] == "completed"
    assert result_payload["error_code"] is None
    assert result_payload["latest_job"]["status"] == "completed"
    assert result_payload["result"]["status"] == "completed"
    assert result_payload["result"]["outcome"] == "success"
    assert result_payload["result"]["failure_code"] is None
    assert result_payload["result"]["sentiment"]["label"] == "bullish"
    assert result_payload["result"]["xai_display"]["evidence"][0]["excerpt"] == (
        "Revenue growth stayed ahead of expectations."
    )
    assert result_payload["result"]["xai_display"]["evidence"][0]["keywords"] == [
        "Revenue",
        "expectations",
    ]
    assert result_payload["result"]["xai_display"]["evidence"][0]["keyword_spans"][0] == {
        "text": "Revenue",
        "start_char": 0,
        "end_char": 7,
        "importance_score": 0.12,
    }
    assert result_payload["result"]["xai_display"]["evidence"][0]["sentiment_signal"] == "bullish"
    assert result_payload["result"]["localized"] is None
    assert result_payload["result"]["xai"]["highlights"][0]["excerpt"] == (
        "Revenue growth stayed ahead of expectations."
    )


def test_news_result_reuses_stored_localized_payload(monkeypatch) -> None:
    repository = InMemoryEnrichmentRepository()
    service = IngestionService(repository=repository)
    request = ArticleEnrichmentRequest(
        news_id="localized-cache-news-1",
        title="Company beats earnings estimates",
        link="https://example.com/articles/localized-cache-news-1",
        ticker=["AAPL"],
        source="Reuters",
    )
    payload = _build_completed_payload(request).model_copy(
        update={"localized": _build_localized_payload()}
    )
    repository.save_enrichment_result(
        SaveEnrichmentRequest(raw_news=request, enrichment=payload)
    )

    monkeypatch.setattr(ingestion_route_module, "service", service)

    client = TestClient(app)
    response = client.get("/api/v1/news/localized-cache-news-1/result")

    assert response.status_code == 200
    body = response.json()
    assert body["result"]["localized"]["title"] == "회사가 실적 예상치를 웃돌았다"
    assert body["result"]["headline_ko"] == "회사가 실적 예상치를 웃돌았다"
    assert body["result"]["localized"]["content"] == (
        "회사는 매출 성장이 예상치를 웃돌았고 경영진은 안정적인 수요를 강조했다."
    )
    assert body["result"]["content_ko"] == (
        "회사는 매출 성장이 예상치를 웃돌았고 경영진은 안정적인 수요를 강조했다."
    )
    assert body["result"]["localized"]["summary_3lines"][0]["text"] == "매출 성장이 예상치를 웃돌았다."
    assert body["result"]["summary_3lines_ko"][0] == "매출 성장이 예상치를 웃돌았다."
    assert body["result"]["xai_ko"] is None


def test_news_intake_reuses_existing_completed_result(monkeypatch) -> None:
    repository = InMemoryEnrichmentRepository()
    service = IngestionService(repository=repository)
    request = ArticleEnrichmentRequest(
        news_id="existing-completed-news-1",
        title="Company beats earnings estimates",
        link="https://example.com/articles/existing-completed-news-1",
        ticker=["AAPL"],
        source="Reuters",
    )
    payload = _build_completed_payload(request).model_copy(
        update={"localized": _build_localized_payload()}
    )
    repository.save_enrichment_result(
        SaveEnrichmentRequest(raw_news=request, enrichment=payload)
    )

    monkeypatch.setattr(ingestion_route_module, "service", service)

    client = TestClient(app)
    response = client.post(
        "/api/v1/news/intake",
        json={
            "news_id": "existing-completed-news-1",
            "title": "Company beats earnings estimates",
            "link": "https://example.com/articles/existing-completed-news-1",
            "ticker": ["AAPL"],
            "source": "Reuters",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["queued"] is False
    assert body["processing_state"] == "completed"
    assert body["message"] == "Existing completed enrichment result reused; no new job queued."


def test_news_intake_does_not_reuse_completed_result_for_different_link(monkeypatch) -> None:
    repository = InMemoryEnrichmentRepository()
    service = IngestionService(repository=repository)
    request = ArticleEnrichmentRequest(
        news_id="same-id-different-link-1",
        title="Company beats earnings estimates",
        link="https://example.com/articles/original",
        ticker=["AAPL"],
        source="Reuters",
    )
    payload = _build_completed_payload(request).model_copy(
        update={"localized": _build_localized_payload()}
    )
    repository.save_enrichment_result(
        SaveEnrichmentRequest(raw_news=request, enrichment=payload)
    )

    monkeypatch.setattr(ingestion_route_module, "service", service)

    client = TestClient(app)
    response = client.post(
        "/api/v1/news/intake",
        json={
            "news_id": "same-id-different-link-1",
            "title": "Company beats earnings estimates",
            "link": "https://example.com/articles/changed",
            "ticker": ["AAPL"],
            "source": "Reuters",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["queued"] is True
    assert body["processing_state"] == "queued"


def test_direct_enrich_does_not_reuse_completed_result_for_different_link(monkeypatch) -> None:
    repository = InMemoryEnrichmentRepository()
    service = EnrichmentService(repository=repository)
    original_request = ArticleEnrichmentRequest(
        news_id="direct-same-id-different-link-1",
        title="Company beats earnings estimates",
        link="https://example.com/articles/original",
        ticker=["AAPL"],
        source="Reuters",
    )
    payload = _build_completed_payload(original_request).model_copy(
        update={"localized": _build_localized_payload()}
    )
    repository.save_enrichment_result(
        SaveEnrichmentRequest(raw_news=original_request, enrichment=payload)
    )

    def _run_and_persist(raw_news: ArticleEnrichmentRequest) -> EnrichmentStoragePayload:
        assert str(raw_news.link).rstrip("/") == "https://example.com/articles/changed"
        updated_payload = _build_completed_payload(raw_news)
        repository.save_enrichment_result(
            SaveEnrichmentRequest(raw_news=raw_news, enrichment=updated_payload)
        )
        return updated_payload

    monkeypatch.setattr(enrichment_route_module, "service", service)
    monkeypatch.setattr(service.orchestrator, "run", _run_and_persist)

    client = TestClient(app)
    response = client.post(
        "/api/v1/articles/enrich",
        json={
            "news_id": "direct-same-id-different-link-1",
            "title": "Company beats earnings estimates",
            "link": "https://example.com/articles/changed",
            "ticker": ["AAPL"],
            "source": "Reuters",
        },
    )

    assert response.status_code == 200
    assert response.json()["link"] == "https://example.com/articles/changed"


def test_news_result_exposes_filtered_content_without_error(monkeypatch) -> None:
    repository = InMemoryEnrichmentRepository()
    service = IngestionService(repository=repository)
    job_service = JobProcessingService(repository=repository)

    def _run_and_persist_filtered(raw_news: ArticleEnrichmentRequest) -> EnrichmentStoragePayload:
        payload = _build_filtered_payload(raw_news)
        repository.save_enrichment_result(
            SaveEnrichmentRequest(raw_news=raw_news, enrichment=payload)
        )
        return payload

    monkeypatch.setattr(ingestion_route_module, "service", service)
    monkeypatch.setattr(ingestion_route_module, "job_service", job_service)
    monkeypatch.setattr(job_service.orchestrator, "run", _run_and_persist_filtered)

    client = TestClient(app)
    client.post(
        "/api/v1/news/intake",
        json={
            "news_id": "filtered-news-1",
            "title": "Transcript header only",
            "link": "https://example.com/articles/filtered-news-1",
            "ticker": ["AAPL"],
            "source": "Reuters",
        },
    )

    worker_response = client.post("/api/v1/jobs/process-next")
    worker_payload = worker_response.json()

    assert worker_response.status_code == 200
    assert worker_payload["processing_state"] == "completed"
    assert worker_payload["error_code"] is None
    assert worker_payload["analysis_status"] == "clean_filtered"
    assert worker_payload["analysis_outcome"] == "filtered"

    result_response = client.get("/api/v1/news/filtered-news-1/result")
    result_payload = result_response.json()

    assert result_response.status_code == 200
    assert result_payload["processing_state"] == "completed"
    assert result_payload["error_code"] is None
    assert result_payload["result"]["status"] == "filtered"
    assert result_payload["result"]["outcome"] == "filtered"
    assert result_payload["result"]["error"] is None
    assert result_payload["latest_job"]["status"] == "completed"


def test_enrich_endpoint_returns_immediate_result(monkeypatch) -> None:
    repository = InMemoryEnrichmentRepository()
    service = EnrichmentService(repository=repository)

    def _run_and_persist(raw_news: ArticleEnrichmentRequest) -> EnrichmentStoragePayload:
        payload = _build_completed_payload(raw_news)
        repository.save_enrichment_result(
            SaveEnrichmentRequest(raw_news=raw_news, enrichment=payload)
        )
        return payload

    monkeypatch.setattr(enrichment_route_module, "service", service)
    monkeypatch.setattr(service.orchestrator, "run", _run_and_persist)

    client = TestClient(app)
    response = client.post(
        "/api/v1/articles/enrich",
        json={
            "news_id": "enrich-news-1",
            "title": "Company beats earnings estimates",
            "link": "https://example.com/articles/enrich-news-1",
            "ticker": ["AAPL"],
            "source": "Reuters",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["news_id"] == "enrich-news-1"
    assert body["status"] == "completed"
    assert body["outcome"] == "success"
    assert len(body["summary_3lines"]) == 3
    assert body["localized"] is None


def test_enrich_endpoint_accepts_text_alias_and_returns_direct_text_result(monkeypatch) -> None:
    repository = InMemoryEnrichmentRepository()
    service = EnrichmentService(repository=repository)

    def _run_with_text_and_persist(
        raw_news: ArticleEnrichmentRequest,
        *,
        article_text: str | None = None,
        summary_text: str | None = None,
    ) -> EnrichmentStoragePayload:
        payload = _build_completed_payload(raw_news)
        payload.fetch_result.extraction_source = ArticleTextSource.PROVIDED_SUMMARY_TEXT
        repository.save_enrichment_result(
            SaveEnrichmentRequest(raw_news=raw_news, enrichment=payload)
        )
        return payload

    monkeypatch.setattr(enrichment_route_module, "service", service)
    monkeypatch.setattr(service.orchestrator, "run_with_text", _run_with_text_and_persist)

    client = TestClient(app)
    response = client.post(
        "/api/v1/articles/enrich",
        json={
            "news_id": "enrich-news-text-1",
            "title": "Company beats earnings estimates",
            "link": "https://example.com/articles/enrich-news-text-1",
            "ticker": ["AAPL"],
            "source": "Licensed Provider",
            "text": "Revenue growth stayed ahead of expectations.",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["news_id"] == "enrich-news-text-1"
    assert body["status"] == "completed"
    assert body["outcome"] == "success"
    assert body["summary_3lines"][0]["text"] == "Revenue growth stayed ahead of expectations."


def test_news_intake_text_worker_and_status_flow(monkeypatch) -> None:
    repository = InMemoryEnrichmentRepository()
    service = IngestionService(repository=repository)
    job_service = JobProcessingService(repository=repository)

    def _run_with_text_and_persist(
        raw_news: ArticleEnrichmentRequest,
        *,
        article_text: str | None = None,
        summary_text: str | None = None,
    ) -> EnrichmentStoragePayload:
        payload = _build_completed_payload(raw_news)
        payload.fetch_result.extraction_source = ArticleTextSource.PROVIDED_SUMMARY_TEXT
        repository.save_enrichment_result(
            SaveEnrichmentRequest(raw_news=raw_news, enrichment=payload)
        )
        return payload

    monkeypatch.setattr(ingestion_route_module, "service", service)
    monkeypatch.setattr(ingestion_route_module, "job_service", job_service)
    monkeypatch.setattr(job_service.orchestrator, "run_with_text", _run_with_text_and_persist)

    client = TestClient(app)

    intake_response = client.post(
        "/api/v1/news/intake-text",
        json={
            "news_id": "e2e-news-text-1",
            "title": "Company beats earnings estimates",
            "link": "https://example.com/articles/e2e-news-text-1",
            "ticker": ["AAPL"],
            "source": "Licensed Provider",
            "summary_text": (
                "Revenue growth stayed ahead of expectations. "
                "Management highlighted stable demand and improved margins."
            ),
        },
    )

    assert intake_response.status_code == 200
    intake_payload = intake_response.json()
    assert intake_payload["queued"] is True
    assert intake_payload["processing_state"] == "queued"
    assert intake_payload["job"]["status"] == "queued"

    worker_response = client.post("/api/v1/jobs/process-next")

    assert worker_response.status_code == 200
    worker_payload = worker_response.json()
    assert worker_payload["processed"] is True
    assert worker_payload["retry_scheduled"] is False
    assert worker_payload["processing_state"] == "completed"
    assert worker_payload["error_code"] is None
    assert worker_payload["analysis_status"] == "completed"
    assert worker_payload["analysis_outcome"] == "success"
    assert (
        worker_payload["enrichment"]["fetch_result"]["extraction_source"]
        == "provided_summary_text"
    )
    assert worker_payload["enrichment"]["xai"]["explanation_method"] == "attention_sentence"

    status_response = client.get("/api/v1/news/e2e-news-text-1")
    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["raw_news"]["news_id"] == "e2e-news-text-1"
    assert "summary_text" not in status_payload["raw_news"]

    stored_raw_news = repository.get_raw_news("e2e-news-text-1")
    assert stored_raw_news is not None
    assert not hasattr(stored_raw_news, "summary_text")


def test_news_intake_accepts_text_alias_and_queues_direct_text(monkeypatch) -> None:
    repository = InMemoryEnrichmentRepository()
    service = IngestionService(repository=repository)
    job_service = JobProcessingService(repository=repository)

    def _run_with_text_and_persist(
        raw_news: ArticleEnrichmentRequest,
        *,
        article_text: str | None = None,
        summary_text: str | None = None,
    ) -> EnrichmentStoragePayload:
        payload = _build_completed_payload(raw_news)
        payload.fetch_result.extraction_source = ArticleTextSource.PROVIDED_SUMMARY_TEXT
        repository.save_enrichment_result(
            SaveEnrichmentRequest(raw_news=raw_news, enrichment=payload)
        )
        return payload

    monkeypatch.setattr(ingestion_route_module, "service", service)
    monkeypatch.setattr(ingestion_route_module, "job_service", job_service)
    monkeypatch.setattr(job_service.orchestrator, "run_with_text", _run_with_text_and_persist)

    client = TestClient(app)
    intake_response = client.post(
        "/api/v1/news/intake",
        json={
            "news_id": "e2e-news-text-legacy-1",
            "title": "Company beats earnings estimates",
            "link": "https://example.com/articles/e2e-news-text-legacy-1",
            "ticker": ["AAPL"],
            "source": "Licensed Provider",
            "text": "Revenue growth stayed ahead of expectations.",
        },
    )

    assert intake_response.status_code == 200
    assert intake_response.json()["queued"] is True
    assert intake_response.json()["processing_state"] == "queued"

    worker_response = client.post("/api/v1/jobs/process-next")
    assert worker_response.status_code == 200
    assert worker_response.json()["processing_state"] == "completed"
    assert (
        worker_response.json()["enrichment"]["fetch_result"]["extraction_source"]
        == "provided_summary_text"
    )


def test_news_intake_accepts_article_body_alias_and_skips_remote_fetch(monkeypatch) -> None:
    repository = InMemoryEnrichmentRepository()
    service = IngestionService(repository=repository)
    job_service = JobProcessingService(repository=repository)

    captured_text: dict[str, str | None] = {}

    def _run_with_text_and_persist(
        raw_news: ArticleEnrichmentRequest,
        *,
        article_text: str | None = None,
        summary_text: str | None = None,
    ) -> EnrichmentStoragePayload:
        captured_text["article_text"] = article_text
        captured_text["summary_text"] = summary_text
        payload = _build_completed_payload(raw_news)
        payload.fetch_result.extraction_source = ArticleTextSource.PROVIDED_ARTICLE_TEXT
        repository.save_enrichment_result(
            SaveEnrichmentRequest(raw_news=raw_news, enrichment=payload)
        )
        return payload

    def _run_should_not_execute(*args, **kwargs):
        raise AssertionError("Direct article body aliases should not fall back to URL fetch.")

    monkeypatch.setattr(ingestion_route_module, "service", service)
    monkeypatch.setattr(ingestion_route_module, "job_service", job_service)
    monkeypatch.setattr(job_service.orchestrator, "run_with_text", _run_with_text_and_persist)
    monkeypatch.setattr(job_service.orchestrator, "run", _run_should_not_execute)

    client = TestClient(app)
    intake_response = client.post(
        "/api/v1/news/intake",
        json={
            "news_id": "e2e-news-article-body-alias-1",
            "title": "Yahoo article with upstream text",
            "link": "https://finance.yahoo.com/news/example-article",
            "ticker": ["AAPL"],
            "source": "Yahoo Finance",
            "articleBody": (
                "Revenue growth stayed ahead of expectations. "
                "Management highlighted stable demand and improved margins. "
                "Investors are watching whether guidance remains intact."
            ),
        },
    )

    assert intake_response.status_code == 200

    worker_response = client.post("/api/v1/jobs/process-next")
    assert worker_response.status_code == 200
    assert worker_response.json()["processing_state"] == "completed"
    assert captured_text["article_text"] is not None
    assert "Revenue growth" in captured_text["article_text"]
    assert captured_text["summary_text"] is None
    assert (
        worker_response.json()["enrichment"]["fetch_result"]["extraction_source"]
        == "provided_article_text"
    )


def test_direct_text_request_rejects_empty_placeholder_summary() -> None:
    try:
        DirectTextEnrichmentRequest(
            news_id="direct-text-empty-1",
            title="Placeholder summary",
            link="https://example.com/articles/direct-text-empty-1",
            ticker=["AAPL"],
            source="Licensed Provider",
            summary_text="EMPTY",
        )
    except ValidationError as exc:
        assert "Either article_text or summary_text must be provided." in str(exc)
    else:
        raise AssertionError("Expected EMPTY summary placeholder to be rejected.")


def test_news_intake_treats_empty_placeholder_as_missing_text(monkeypatch) -> None:
    repository = InMemoryEnrichmentRepository()
    service = IngestionService(repository=repository)
    job_service = JobProcessingService(repository=repository)

    def _run_and_persist(raw_news: ArticleEnrichmentRequest) -> EnrichmentStoragePayload:
        payload = _build_completed_payload(raw_news)
        repository.save_enrichment_result(
            SaveEnrichmentRequest(raw_news=raw_news, enrichment=payload)
        )
        return payload

    def _run_with_text_should_not_execute(*args, **kwargs):
        raise AssertionError("summary_text='EMPTY' should not be treated as direct text.")

    monkeypatch.setattr(ingestion_route_module, "service", service)
    monkeypatch.setattr(ingestion_route_module, "job_service", job_service)
    monkeypatch.setattr(job_service.orchestrator, "run", _run_and_persist)
    monkeypatch.setattr(
        job_service.orchestrator,
        "run_with_text",
        _run_with_text_should_not_execute,
    )

    client = TestClient(app)
    intake_response = client.post(
        "/api/v1/news/intake",
        json={
            "news_id": "e2e-news-empty-placeholder-1",
            "title": "Placeholder summary should crawl",
            "link": "https://example.com/articles/e2e-news-empty-placeholder-1",
            "ticker": ["AAPL"],
            "source": "Licensed Provider",
            "summary_text": "EMPTY",
        },
    )

    assert intake_response.status_code == 200
    assert intake_response.json()["queued"] is True
    assert intake_response.json()["processing_state"] == "queued"

    worker_response = client.post("/api/v1/jobs/process-next")
    assert worker_response.status_code == 200
    worker_payload = worker_response.json()
    assert worker_payload["processed"] is True
    assert worker_payload["processing_state"] == "completed"
    assert worker_payload["analysis_status"] == "completed"
    assert (
        worker_payload["enrichment"]["fetch_result"]["extraction_source"]
        == "paragraph_blocks"
    )


def test_enrich_text_endpoint_returns_immediate_direct_text_result(monkeypatch) -> None:
    repository = InMemoryEnrichmentRepository()
    service = EnrichmentService(repository=repository)

    def _run_with_text_and_persist(
        raw_news: ArticleEnrichmentRequest,
        *,
        article_text: str | None = None,
        summary_text: str | None = None,
    ) -> EnrichmentStoragePayload:
        payload = _build_completed_payload(raw_news)
        payload.fetch_result.extraction_source = ArticleTextSource.PROVIDED_ARTICLE_TEXT
        repository.save_enrichment_result(
            SaveEnrichmentRequest(raw_news=raw_news, enrichment=payload)
        )
        return payload

    monkeypatch.setattr(enrichment_route_module, "service", service)
    monkeypatch.setattr(service.orchestrator, "run_with_text", _run_with_text_and_persist)

    client = TestClient(app)
    response = client.post(
        "/api/v1/articles/enrich-text",
        json={
            "news_id": "direct-text-news-1",
            "title": "Company beats earnings estimates",
            "link": "https://example.com/articles/direct-text-news-1",
            "ticker": ["AAPL"],
            "source": "Reuters",
            "article_text": (
                "Revenue growth stayed ahead of expectations. "
                "Management highlighted stable demand and improved margins. "
                "Investors are watching whether guidance remains intact."
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["news_id"] == "direct-text-news-1"
    assert body["status"] == "completed"
    assert body["localized"] is None


def test_direct_enrichment_can_wait_on_worker_backed_flow(monkeypatch) -> None:
    repository = InMemoryEnrichmentRepository()
    service = EnrichmentService(repository=repository)
    payload = _build_completed_payload(
        ArticleEnrichmentRequest(
            news_id="render-queued-enrich-1",
            title="Queued direct enrich",
            link="https://example.com/articles/render-queued-enrich-1",
            ticker=["AAPL"],
            source="Reuters",
        )
    )

    async def _submit_and_wait(request: FlexibleTextEnrichmentRequest) -> EnrichmentStoragePayload:
        assert request.news_id == "render-queued-enrich-1"
        return payload

    class StubDirectEnrichmentJobService:
        async def submit_and_wait(
            self,
            request: FlexibleTextEnrichmentRequest,
        ) -> EnrichmentStoragePayload:
            return await _submit_and_wait(request)

    monkeypatch.setattr(enrichment_route_module, "service", service)
    monkeypatch.setattr(service, "_direct_enrichment_job_service", StubDirectEnrichmentJobService())
    monkeypatch.setattr(
        "app.services.enrichment_service.settings",
        replace(
            __import__("app.services.enrichment_service", fromlist=["settings"]).settings,
            use_worker_backed_direct_enrichment=True,
        ),
    )

    client = TestClient(app)
    response = client.post(
        "/api/v1/articles/enrich",
        json={
            "news_id": "render-queued-enrich-1",
            "title": "Queued direct enrich",
            "link": "https://example.com/articles/render-queued-enrich-1",
            "ticker": ["AAPL"],
            "source": "Reuters",
        },
    )

    assert response.status_code == 200
    assert response.json()["news_id"] == "render-queued-enrich-1"
    assert response.json()["status"] == "completed"


def test_process_next_endpoint_is_disabled_on_render_web(monkeypatch) -> None:
    monkeypatch.setattr(
        ingestion_route_module,
        "settings",
        replace(ingestion_route_module.settings, enable_job_process_api=False),
    )

    client = TestClient(app)
    response = client.post("/api/v1/jobs/process-next")

    assert response.status_code == 503
    assert "Job processing API is disabled" in response.json()["detail"]


def test_news_routes_accept_url_shaped_news_id(monkeypatch) -> None:
    repository = InMemoryEnrichmentRepository()
    service = IngestionService(repository=repository)
    job_service = JobProcessingService(repository=repository)
    url_shaped_news_id = "https://www.reuters.com/world/us/test-article"

    def _run_and_persist(raw_news: ArticleEnrichmentRequest) -> EnrichmentStoragePayload:
        payload = _build_completed_payload(raw_news)
        repository.save_enrichment_result(
            SaveEnrichmentRequest(raw_news=raw_news, enrichment=payload)
        )
        return payload

    monkeypatch.setattr(ingestion_route_module, "service", service)
    monkeypatch.setattr(ingestion_route_module, "job_service", job_service)
    monkeypatch.setattr(job_service.orchestrator, "run", _run_and_persist)

    client = TestClient(app)

    intake_response = client.post(
        "/api/v1/news/intake",
        json={
            "news_id": url_shaped_news_id,
            "title": "URL-shaped news id",
            "link": "https://example.com/articles/url-shaped-news-id",
            "ticker": ["AAPL"],
            "source": "Reuters",
        },
    )

    assert intake_response.status_code == 200
    worker_response = client.post("/api/v1/jobs/process-next")
    assert worker_response.status_code == 200

    encoded_news_id = "https:%2F%2Fwww.reuters.com%2Fworld%2Fus%2Ftest-article"
    status_response = client.get(f"/api/v1/news/{encoded_news_id}")
    result_response = client.get(f"/api/v1/news/{encoded_news_id}/result")

    assert status_response.status_code == 200
    assert status_response.json()["news_id"] == url_shaped_news_id
    assert result_response.status_code == 200
    assert result_response.json()["news_id"] == url_shaped_news_id