from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from app.db import (
    connect_postgres,
    connect_sqlite,
    get_default_db_path,
    initialize_sqlite_database,
)
from app.schemas.enrichment import ArticleEnrichmentRequest
from app.schemas.enrichment import normalize_optional_text_input
from app.schemas.ingestion import (
    EnrichmentJobRecord,
    EnrichmentJobStatus,
    RawNewsIngestionRequest,
)
from app.schemas.mixed import TickerSentimentObservation
from app.schemas.operations import (
    CountMetric,
    OperationalStatsResponse,
    PublisherOutcomeMetric,
    PublisherFetchFailureMetric,
)
from app.schemas.storage import AnalysisOutcome, AnalysisStatus, EnrichmentStoragePayload


@dataclass(frozen=True, slots=True)
class SaveEnrichmentRequest:
    """Persistence command separating raw news metadata from AI enrichment output."""

    raw_news: ArticleEnrichmentRequest
    enrichment: EnrichmentStoragePayload


class EnrichmentRepository(Protocol):
    """Repository boundary for raw news storage, queueing, and enrichment persistence."""

    def upsert_raw_news(self, raw_news: ArticleEnrichmentRequest) -> None:
        """Store or update the raw news metadata received from the upstream system."""

    def get_raw_news(self, news_id: str) -> ArticleEnrichmentRequest | None:
        """Return raw news metadata for a known article id."""

    def get_active_job(self, news_id: str) -> EnrichmentJobRecord | None:
        """Return an active queued/processing job for the article when it exists."""

    def get_latest_job(self, news_id: str) -> EnrichmentJobRecord | None:
        """Return the most recent job record for an article."""

    def get_news_snapshot(
        self,
        news_id: str,
    ) -> tuple[
        ArticleEnrichmentRequest | None,
        EnrichmentJobRecord | None,
        EnrichmentStoragePayload | None,
    ]:
        """Return raw news, latest job, and enrichment result in one repository round trip."""

    def create_enrichment_job(
        self,
        news_id: str,
        *,
        max_attempts: int = 3,
    ) -> EnrichmentJobRecord:
        """Create a queued enrichment job for a known raw news item."""

    def claim_next_enrichment_job(self) -> EnrichmentJobRecord | None:
        """Atomically claim the next queued enrichment job for processing."""

    def mark_job_completed(
        self,
        job_id: str,
        *,
        analysis_status: AnalysisStatus,
    ) -> EnrichmentJobRecord | None:
        """Mark the claimed job as completed."""

    def mark_job_failed(
        self,
        job_id: str,
        *,
        error_message: str,
        analysis_status: AnalysisStatus | None = None,
    ) -> EnrichmentJobRecord | None:
        """Mark the claimed job as failed and store the latest error information."""

    def requeue_job(
        self,
        job_id: str,
        *,
        error_message: str,
        next_retry_at: datetime,
        analysis_status: AnalysisStatus | None = None,
    ) -> EnrichmentJobRecord | None:
        """Return a claimed job back to the queue because a retry should happen later."""

    def get_enrichment_result(self, news_id: str) -> EnrichmentStoragePayload | None:
        """Return the saved enrichment payload for a known article id."""

    def save_enrichment_result(self, payload: SaveEnrichmentRequest) -> None:
        """Persist the enrichment result alongside the raw news identifier."""

    def list_recent_ticker_sentiments(self, ticker: str) -> list[TickerSentimentObservation]:
        """Return recent ticker sentiment observations for mixed detection."""

    def get_operational_stats(self) -> OperationalStatsResponse:
        """Return aggregated operational metrics for fetch failures and job states."""

    def clear_raw_news_text_inputs(self, news_id: str) -> None:
        """Remove provider-supplied raw text after processing is finished."""


@dataclass(slots=True)
class InMemoryEnrichmentRepository:
    """Simple in-memory repository kept as a development fallback."""

    _saved_results: list[SaveEnrichmentRequest] = field(default_factory=list)
    _raw_news_by_id: dict[str, ArticleEnrichmentRequest] = field(default_factory=dict)
    _jobs_by_id: dict[str, EnrichmentJobRecord] = field(default_factory=dict)

    def upsert_raw_news(self, raw_news: ArticleEnrichmentRequest) -> None:
        self._raw_news_by_id[raw_news.news_id] = raw_news

    def get_raw_news(self, news_id: str) -> ArticleEnrichmentRequest | None:
        return self._raw_news_by_id.get(news_id)

    def clear_raw_news_text_inputs(self, news_id: str) -> None:
        raw_news = self._raw_news_by_id.get(news_id)
        if raw_news is None:
            return
        if not (
            (getattr(raw_news, "article_text", None) or "").strip()
            or (getattr(raw_news, "summary_text", None) or "").strip()
        ):
            return
        self._raw_news_by_id[news_id] = ArticleEnrichmentRequest(
            news_id=raw_news.news_id,
            title=raw_news.title,
            link=raw_news.link,
            ticker=raw_news.ticker,
            source=raw_news.source,
            published_at=raw_news.published_at,
        )

    def get_active_job(self, news_id: str) -> EnrichmentJobRecord | None:
        active_jobs = [
            job
            for job in self._jobs_by_id.values()
            if job.news_id == news_id
            and job.status in {
                EnrichmentJobStatus.QUEUED,
                EnrichmentJobStatus.RETRY_PENDING,
                EnrichmentJobStatus.PROCESSING,
            }
        ]
        if not active_jobs:
            return None
        return max(active_jobs, key=lambda job: job.created_at)

    def get_latest_job(self, news_id: str) -> EnrichmentJobRecord | None:
        jobs = [job for job in self._jobs_by_id.values() if job.news_id == news_id]
        if not jobs:
            return None
        return max(jobs, key=lambda job: job.created_at)

    def get_news_snapshot(
        self,
        news_id: str,
    ) -> tuple[
        ArticleEnrichmentRequest | None,
        EnrichmentJobRecord | None,
        EnrichmentStoragePayload | None,
    ]:
        return (
            self.get_raw_news(news_id),
            self.get_latest_job(news_id),
            self.get_enrichment_result(news_id),
        )

    def create_enrichment_job(
        self,
        news_id: str,
        *,
        max_attempts: int = 3,
    ) -> EnrichmentJobRecord:
        now = datetime.now(timezone.utc)
        job = EnrichmentJobRecord(
            job_id=str(uuid4()),
            news_id=news_id,
            status=EnrichmentJobStatus.QUEUED,
            attempts=0,
            max_attempts=max_attempts,
            last_error=None,
            last_analysis_status=None,
            created_at=now,
            updated_at=now,
            next_retry_at=None,
            started_at=None,
            completed_at=None,
        )
        self._jobs_by_id[job.job_id] = job
        return job

    def claim_next_enrichment_job(self) -> EnrichmentJobRecord | None:
        queued_jobs = [
            job
            for job in self._jobs_by_id.values()
            if job.status in {EnrichmentJobStatus.QUEUED, EnrichmentJobStatus.RETRY_PENDING}
            and (
                job.status == EnrichmentJobStatus.QUEUED
                or job.next_retry_at is None
                or job.next_retry_at <= datetime.now(timezone.utc)
            )
        ]
        if not queued_jobs:
            return None

        target = min(queued_jobs, key=lambda job: job.created_at)
        now = datetime.now(timezone.utc)
        claimed = target.model_copy(
            update={
                "status": EnrichmentJobStatus.PROCESSING,
                "attempts": target.attempts + 1,
                "updated_at": now,
                "next_retry_at": None,
                "started_at": now,
            }
        )
        self._jobs_by_id[target.job_id] = claimed
        return claimed

    def mark_job_completed(
        self,
        job_id: str,
        *,
        analysis_status: AnalysisStatus,
    ) -> EnrichmentJobRecord | None:
        existing = self._jobs_by_id.get(job_id)
        if existing is None:
            return None
        now = datetime.now(timezone.utc)
        updated = existing.model_copy(
            update={
                "status": EnrichmentJobStatus.COMPLETED,
                "updated_at": now,
                "completed_at": now,
                "last_error": None,
                "last_analysis_status": analysis_status,
            }
        )
        self._jobs_by_id[job_id] = updated
        return updated

    def mark_job_failed(
        self,
        job_id: str,
        *,
        error_message: str,
        analysis_status: AnalysisStatus | None = None,
    ) -> EnrichmentJobRecord | None:
        existing = self._jobs_by_id.get(job_id)
        if existing is None:
            return None
        now = datetime.now(timezone.utc)
        updated = existing.model_copy(
            update={
                "status": EnrichmentJobStatus.FAILED,
                "updated_at": now,
                "completed_at": now,
                "last_error": error_message,
                "last_analysis_status": analysis_status,
            }
        )
        self._jobs_by_id[job_id] = updated
        return updated

    def requeue_job(
        self,
        job_id: str,
        *,
        error_message: str,
        next_retry_at: datetime,
        analysis_status: AnalysisStatus | None = None,
    ) -> EnrichmentJobRecord | None:
        existing = self._jobs_by_id.get(job_id)
        if existing is None:
            return None
        now = datetime.now(timezone.utc)
        updated = existing.model_copy(
            update={
                "status": EnrichmentJobStatus.RETRY_PENDING,
                "updated_at": now,
                "next_retry_at": next_retry_at,
                "completed_at": None,
                "last_error": error_message,
                "last_analysis_status": analysis_status,
            }
        )
        self._jobs_by_id[job_id] = updated
        return updated

    def get_enrichment_result(self, news_id: str) -> EnrichmentStoragePayload | None:
        for item in reversed(self._saved_results):
            if item.enrichment.news_id == news_id:
                return item.enrichment
        return None

    def save_enrichment_result(self, payload: SaveEnrichmentRequest) -> None:
        self.upsert_raw_news(payload.raw_news)
        self._saved_results.append(payload)

    def list_recent_ticker_sentiments(self, ticker: str) -> list[TickerSentimentObservation]:
        normalized_ticker = ticker.strip().upper()
        results: list[TickerSentimentObservation] = []

        for item in self._saved_results:
            if item.enrichment.sentiment is None:
                continue
            if not item.raw_news.ticker or normalized_ticker not in item.raw_news.ticker:
                continue

            results.append(
                TickerSentimentObservation(
                    ticker=normalized_ticker,
                    news_id=item.enrichment.news_id,
                    score=item.enrichment.sentiment.score,
                    label=item.enrichment.sentiment.label,
                    confidence=item.enrichment.sentiment.confidence,
                    analyzed_at=item.enrichment.analyzed_at,
                )
            )

        return results

    def get_operational_stats(self) -> OperationalStatsResponse:
        return _build_operational_stats(
            enrichments=[item.enrichment for item in self._saved_results],
            jobs=list(self._jobs_by_id.values()),
        )


@dataclass(slots=True)
class SQLiteEnrichmentRepository:
    """SQLite-backed repository for raw news metadata, queue records, and enrichments."""

    db_path: Path = field(default_factory=get_default_db_path)

    def __post_init__(self) -> None:
        self.db_path = initialize_sqlite_database(self.db_path)

    def upsert_raw_news(self, raw_news: ArticleEnrichmentRequest) -> None:
        now = _utc_now()
        tickers = raw_news.ticker or []
        article_text = normalize_optional_text_input(getattr(raw_news, "article_text", None))
        summary_text = normalize_optional_text_input(getattr(raw_news, "summary_text", None))
        with connect_sqlite(self.db_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO raw_news (
                    news_id,
                    title,
                    link,
                    source,
                    published_at,
                    provided_article_text,
                    provided_summary_text,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(news_id) DO UPDATE SET
                    title = excluded.title,
                    link = excluded.link,
                    source = excluded.source,
                    published_at = excluded.published_at,
                    provided_article_text = excluded.provided_article_text,
                    provided_summary_text = excluded.provided_summary_text,
                    updated_at = excluded.updated_at
                """,
                (
                    raw_news.news_id,
                    raw_news.title,
                    str(raw_news.link),
                    raw_news.source,
                    _datetime_to_storage(raw_news.published_at),
                    article_text,
                    summary_text,
                    now,
                    now,
                ),
            )
            connection.execute(
                "DELETE FROM raw_news_tickers WHERE news_id = ?",
                (raw_news.news_id,),
            )
            connection.executemany(
                """
                INSERT INTO raw_news_tickers (news_id, ticker)
                VALUES (?, ?)
                """,
                [(raw_news.news_id, ticker) for ticker in tickers],
            )

    def get_raw_news(self, news_id: str) -> ArticleEnrichmentRequest | None:
        with connect_sqlite(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT
                    news_id,
                    title,
                    link,
                    source,
                    published_at,
                    provided_article_text,
                    provided_summary_text
                FROM raw_news
                WHERE news_id = ?
                """,
                (news_id,),
            ).fetchone()
            if row is None:
                return None
            ticker_rows = connection.execute(
                """
                SELECT ticker
                FROM raw_news_tickers
                WHERE news_id = ?
                ORDER BY ticker ASC
                """,
                (news_id,),
            ).fetchall()

        return _build_raw_news_request(
            news_id=row["news_id"],
            title=row["title"],
            link=row["link"],
            ticker=[item["ticker"] for item in ticker_rows] or None,
            source=row["source"],
            published_at=row["published_at"],
            article_text=row["provided_article_text"],
            summary_text=row["provided_summary_text"],
        )

    def clear_raw_news_text_inputs(self, news_id: str) -> None:
        with connect_sqlite(self.db_path) as connection:
            connection.execute(
                """
                UPDATE raw_news
                SET
                    provided_article_text = NULL,
                    provided_summary_text = NULL,
                    updated_at = ?
                WHERE news_id = ?
                """,
                (_utc_now(), news_id),
            )

    def get_active_job(self, news_id: str) -> EnrichmentJobRecord | None:
        with connect_sqlite(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT *
                FROM enrichment_jobs
                WHERE news_id = ?
                  AND status IN (?, ?, ?)
                ORDER BY updated_at DESC, created_at DESC
                LIMIT 1
                """,
                (
                    news_id,
                    EnrichmentJobStatus.QUEUED.value,
                    EnrichmentJobStatus.RETRY_PENDING.value,
                    EnrichmentJobStatus.PROCESSING.value,
                ),
            ).fetchone()
        return _job_from_row(row)

    def get_latest_job(self, news_id: str) -> EnrichmentJobRecord | None:
        with connect_sqlite(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT *
                FROM enrichment_jobs
                WHERE news_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (news_id,),
            ).fetchone()
        return _job_from_row(row)

    def get_news_snapshot(
        self,
        news_id: str,
    ) -> tuple[
        ArticleEnrichmentRequest | None,
        EnrichmentJobRecord | None,
        EnrichmentStoragePayload | None,
    ]:
        with connect_sqlite(self.db_path) as connection:
            raw_news_row = connection.execute(
                """
                SELECT
                    news_id,
                    title,
                    link,
                    source,
                    published_at,
                    provided_article_text,
                    provided_summary_text
                FROM raw_news
                WHERE news_id = ?
                """,
                (news_id,),
            ).fetchone()
            ticker_rows = (
                connection.execute(
                    """
                    SELECT ticker
                    FROM raw_news_tickers
                    WHERE news_id = ?
                    ORDER BY ticker ASC
                    """,
                    (news_id,),
                ).fetchall()
                if raw_news_row is not None
                else []
            )
            latest_job_row = connection.execute(
                """
                SELECT *
                FROM enrichment_jobs
                WHERE news_id = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (news_id,),
            ).fetchone()
            enrichment_row = connection.execute(
                """
                SELECT payload_json
                FROM enrichment_results
                WHERE news_id = ?
                """,
                (news_id,),
            ).fetchone()

        raw_news = None
        if raw_news_row is not None:
            raw_news = _build_raw_news_request(
                news_id=raw_news_row["news_id"],
                title=raw_news_row["title"],
                link=raw_news_row["link"],
                ticker=[item["ticker"] for item in ticker_rows] or None,
                source=raw_news_row["source"],
                published_at=raw_news_row["published_at"],
                article_text=raw_news_row["provided_article_text"],
                summary_text=raw_news_row["provided_summary_text"],
            )

        enrichment = None
        if enrichment_row is not None:
            enrichment = _payload_from_storage(enrichment_row["payload_json"])

        return raw_news, _job_from_row(latest_job_row), enrichment

    def create_enrichment_job(
        self,
        news_id: str,
        *,
        max_attempts: int = 3,
    ) -> EnrichmentJobRecord:
        now = _utc_now()
        job_id = str(uuid4())
        with connect_sqlite(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO enrichment_jobs (
                    job_id,
                    news_id,
                    status,
                    attempts,
                    max_attempts,
                    last_error,
                    last_analysis_status,
                    created_at,
                    updated_at,
                    next_retry_at,
                    started_at,
                    completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    news_id,
                    EnrichmentJobStatus.QUEUED.value,
                    0,
                    max_attempts,
                    None,
                    None,
                    now,
                    now,
                    None,
                    None,
                    None,
                ),
            )
            row = connection.execute(
                "SELECT * FROM enrichment_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        job = _job_from_row(row)
        if job is None:
            raise RuntimeError("Failed to create enrichment job record.")
        return job

    def claim_next_enrichment_job(self) -> EnrichmentJobRecord | None:
        with connect_sqlite(self.db_path) as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT *
                FROM enrichment_jobs
                WHERE (
                    status = ?
                ) OR (
                    status = ?
                    AND next_retry_at IS NOT NULL
                    AND next_retry_at <= ?
                )
                ORDER BY
                    CASE
                        WHEN status = ? THEN updated_at
                        ELSE next_retry_at
                    END ASC,
                    created_at ASC
                LIMIT 1
                """,
                (
                    EnrichmentJobStatus.QUEUED.value,
                    EnrichmentJobStatus.RETRY_PENDING.value,
                    _utc_now(),
                    EnrichmentJobStatus.QUEUED.value,
                ),
            ).fetchone()
            if row is None:
                return None

            now = _utc_now()
            updated = connection.execute(
                """
                UPDATE enrichment_jobs
                SET status = ?,
                    attempts = attempts + 1,
                    updated_at = ?,
                    next_retry_at = ?,
                    started_at = ?
                WHERE job_id = ?
                  AND status IN (?, ?)
                """,
                (
                    EnrichmentJobStatus.PROCESSING.value,
                    now,
                    None,
                    now,
                    row["job_id"],
                    EnrichmentJobStatus.QUEUED.value,
                    EnrichmentJobStatus.RETRY_PENDING.value,
                ),
            )
            if updated.rowcount == 0:
                return None

            claimed_row = connection.execute(
                "SELECT * FROM enrichment_jobs WHERE job_id = ?",
                (row["job_id"],),
            ).fetchone()
        return _job_from_row(claimed_row)

    def mark_job_completed(
        self,
        job_id: str,
        *,
        analysis_status: AnalysisStatus,
    ) -> EnrichmentJobRecord | None:
        return self._update_job_terminal_state(
            job_id=job_id,
            status=EnrichmentJobStatus.COMPLETED,
            error_message=None,
            analysis_status=analysis_status,
        )

    def mark_job_failed(
        self,
        job_id: str,
        *,
        error_message: str,
        analysis_status: AnalysisStatus | None = None,
    ) -> EnrichmentJobRecord | None:
        return self._update_job_terminal_state(
            job_id=job_id,
            status=EnrichmentJobStatus.FAILED,
            error_message=error_message,
            analysis_status=analysis_status,
        )

    def requeue_job(
        self,
        job_id: str,
        *,
        error_message: str,
        next_retry_at: datetime,
        analysis_status: AnalysisStatus | None = None,
    ) -> EnrichmentJobRecord | None:
        now = _utc_now()
        with connect_sqlite(self.db_path) as connection:
            connection.execute(
                """
                UPDATE enrichment_jobs
                SET status = ?,
                    updated_at = ?,
                    next_retry_at = ?,
                    completed_at = ?,
                    last_error = ?,
                    last_analysis_status = ?
                WHERE job_id = ?
                """,
                (
                    EnrichmentJobStatus.RETRY_PENDING.value,
                    now,
                    next_retry_at.isoformat(),
                    None,
                    error_message,
                    analysis_status.value if analysis_status is not None else None,
                    job_id,
                ),
            )
            row = connection.execute(
                "SELECT * FROM enrichment_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        return _job_from_row(row)

    def get_enrichment_result(self, news_id: str) -> EnrichmentStoragePayload | None:
        with connect_sqlite(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT payload_json
                FROM enrichment_results
                WHERE news_id = ?
                """,
                (news_id,),
            ).fetchone()
        if row is None:
            return None
        return _payload_from_storage(row["payload_json"])

    def save_enrichment_result(self, payload: SaveEnrichmentRequest) -> None:
        self.upsert_raw_news(payload.raw_news)
        now = _utc_now()
        serialized_payload = payload.enrichment.model_dump_json()

        with connect_sqlite(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO enrichment_results (
                    news_id,
                    title,
                    link,
                    payload_json,
                    analysis_status,
                    analysis_outcome,
                    analyzed_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(news_id) DO UPDATE SET
                    title = excluded.title,
                    link = excluded.link,
                    payload_json = excluded.payload_json,
                    analysis_status = excluded.analysis_status,
                    analysis_outcome = excluded.analysis_outcome,
                    analyzed_at = excluded.analyzed_at,
                    updated_at = excluded.updated_at
                """,
                (
                    payload.enrichment.news_id,
                    payload.enrichment.title,
                    str(payload.enrichment.link),
                    serialized_payload,
                    payload.enrichment.analysis_status.value,
                    payload.enrichment.analysis_outcome.value,
                    payload.enrichment.analyzed_at.isoformat(),
                    now,
                ),
            )

    def list_recent_ticker_sentiments(self, ticker: str) -> list[TickerSentimentObservation]:
        normalized_ticker = ticker.strip().upper()
        with connect_sqlite(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT er.payload_json
                FROM enrichment_results er
                INNER JOIN raw_news_tickers rnt
                    ON rnt.news_id = er.news_id
                WHERE rnt.ticker = ?
                ORDER BY er.analyzed_at DESC
                LIMIT 50
                """,
                (normalized_ticker,),
            ).fetchall()

        observations: list[TickerSentimentObservation] = []
        for row in rows:
            payload = EnrichmentStoragePayload.model_validate_json(row["payload_json"])
            if payload.sentiment is None:
                continue
            observations.append(
                TickerSentimentObservation(
                    ticker=normalized_ticker,
                    news_id=payload.news_id,
                    score=payload.sentiment.score,
                    label=payload.sentiment.label,
                    confidence=payload.sentiment.confidence,
                    analyzed_at=payload.analyzed_at,
                )
            )
        return observations

    def get_operational_stats(self) -> OperationalStatsResponse:
        with connect_sqlite(self.db_path) as connection:
            enrichment_rows = connection.execute(
                """
                SELECT payload_json
                FROM enrichment_results
                """
            ).fetchall()
            job_rows = connection.execute(
                """
                SELECT *
                FROM enrichment_jobs
                """
            ).fetchall()

        enrichments = [
            EnrichmentStoragePayload.model_validate_json(row["payload_json"])
            for row in enrichment_rows
        ]
        jobs = [_job_from_row(row) for row in job_rows]
        return _build_operational_stats(
            enrichments=enrichments,
            jobs=[job for job in jobs if job is not None],
        )

    def _update_job_terminal_state(
        self,
        *,
        job_id: str,
        status: EnrichmentJobStatus,
        error_message: str | None,
        analysis_status: AnalysisStatus | None,
    ) -> EnrichmentJobRecord | None:
        now = _utc_now()
        with connect_sqlite(self.db_path) as connection:
            connection.execute(
                """
                UPDATE enrichment_jobs
                SET status = ?,
                    updated_at = ?,
                    completed_at = ?,
                    next_retry_at = ?,
                    last_error = ?,
                    last_analysis_status = ?
                WHERE job_id = ?
                """,
                (
                    status.value,
                    now,
                    now,
                    None,
                    error_message,
                    analysis_status.value if analysis_status is not None else None,
                    job_id,
                ),
            )
            row = connection.execute(
                "SELECT * FROM enrichment_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        return _job_from_row(row)


@dataclass(slots=True)
class PostgresEnrichmentRepository:
    """Postgres-backed repository for production deployments."""

    dsn: str | None = None

    def __post_init__(self) -> None:
        if not self.dsn:
            raise RuntimeError(
                "Postgres repository requires a DSN. "
                "Set GENAI_POSTGRES_DSN or DATABASE_URL."
            )

    def upsert_raw_news(self, raw_news: ArticleEnrichmentRequest) -> None:
        now = _utc_datetime()
        tickers = raw_news.ticker or []
        article_text = normalize_optional_text_input(getattr(raw_news, "article_text", None))
        summary_text = normalize_optional_text_input(getattr(raw_news, "summary_text", None))
        with connect_postgres(self.dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO raw_news (
                        news_id,
                        title,
                        link,
                        source,
                        published_at,
                        provided_article_text,
                        provided_summary_text,
                        created_at,
                        updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(news_id) DO UPDATE SET
                        title = EXCLUDED.title,
                        link = EXCLUDED.link,
                        source = EXCLUDED.source,
                        published_at = EXCLUDED.published_at,
                        provided_article_text = EXCLUDED.provided_article_text,
                        provided_summary_text = EXCLUDED.provided_summary_text,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        raw_news.news_id,
                        raw_news.title,
                        str(raw_news.link),
                        raw_news.source,
                        raw_news.published_at,
                        article_text,
                        summary_text,
                        now,
                        now,
                    ),
                )
                cursor.execute(
                    "DELETE FROM raw_news_tickers WHERE news_id = %s",
                    (raw_news.news_id,),
                )
                if tickers:
                    cursor.executemany(
                        """
                        INSERT INTO raw_news_tickers (news_id, ticker)
                        VALUES (%s, %s)
                        """,
                        [(raw_news.news_id, ticker) for ticker in tickers],
                    )

    def get_raw_news(self, news_id: str) -> ArticleEnrichmentRequest | None:
        with connect_postgres(self.dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        news_id,
                        title,
                        link,
                        source,
                        published_at,
                        provided_article_text,
                        provided_summary_text
                    FROM raw_news
                    WHERE news_id = %s
                    """,
                    (news_id,),
                )
                row = cursor.fetchone()
                if row is None:
                    return None
                cursor.execute(
                    """
                    SELECT ticker
                    FROM raw_news_tickers
                    WHERE news_id = %s
                    ORDER BY ticker ASC
                    """,
                    (news_id,),
                )
                ticker_rows = cursor.fetchall()

        return _build_raw_news_request(
            news_id=row["news_id"],
            title=row["title"],
            link=row["link"],
            ticker=[item["ticker"] for item in ticker_rows] or None,
            source=row["source"],
            published_at=row["published_at"],
            article_text=row["provided_article_text"],
            summary_text=row["provided_summary_text"],
        )

    def clear_raw_news_text_inputs(self, news_id: str) -> None:
        with connect_postgres(self.dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE raw_news
                    SET
                        provided_article_text = NULL,
                        provided_summary_text = NULL,
                        updated_at = %s
                    WHERE news_id = %s
                    """,
                    (_utc_datetime(), news_id),
                )

    def get_active_job(self, news_id: str) -> EnrichmentJobRecord | None:
        with connect_postgres(self.dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM enrichment_jobs
                    WHERE news_id = %s
                      AND status IN (%s, %s, %s)
                    ORDER BY updated_at DESC, created_at DESC
                    LIMIT 1
                    """,
                    (
                        news_id,
                        EnrichmentJobStatus.QUEUED.value,
                        EnrichmentJobStatus.RETRY_PENDING.value,
                        EnrichmentJobStatus.PROCESSING.value,
                    ),
                )
                row = cursor.fetchone()
        return _job_from_row(row)

    def get_latest_job(self, news_id: str) -> EnrichmentJobRecord | None:
        with connect_postgres(self.dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM enrichment_jobs
                    WHERE news_id = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (news_id,),
                )
                row = cursor.fetchone()
        return _job_from_row(row)

    def get_news_snapshot(
        self,
        news_id: str,
    ) -> tuple[
        ArticleEnrichmentRequest | None,
        EnrichmentJobRecord | None,
        EnrichmentStoragePayload | None,
    ]:
        with connect_postgres(self.dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        news_id,
                        title,
                        link,
                        source,
                        published_at,
                        provided_article_text,
                        provided_summary_text
                    FROM raw_news
                    WHERE news_id = %s
                    """,
                    (news_id,),
                )
                raw_news_row = cursor.fetchone()
                ticker_rows = []
                if raw_news_row is not None:
                    cursor.execute(
                        """
                        SELECT ticker
                        FROM raw_news_tickers
                        WHERE news_id = %s
                        ORDER BY ticker ASC
                        """,
                        (news_id,),
                    )
                    ticker_rows = cursor.fetchall()
                cursor.execute(
                    """
                    SELECT *
                    FROM enrichment_jobs
                    WHERE news_id = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (news_id,),
                )
                latest_job_row = cursor.fetchone()
                cursor.execute(
                    """
                    SELECT payload_json
                    FROM enrichment_results
                    WHERE news_id = %s
                    """,
                    (news_id,),
                )
                enrichment_row = cursor.fetchone()

        raw_news = None
        if raw_news_row is not None:
            raw_news = _build_raw_news_request(
                news_id=raw_news_row["news_id"],
                title=raw_news_row["title"],
                link=raw_news_row["link"],
                ticker=[item["ticker"] for item in ticker_rows] or None,
                source=raw_news_row["source"],
                published_at=raw_news_row["published_at"],
                article_text=raw_news_row["provided_article_text"],
                summary_text=raw_news_row["provided_summary_text"],
            )

        enrichment = None
        if enrichment_row is not None:
            enrichment = _payload_from_storage(enrichment_row["payload_json"])

        return raw_news, _job_from_row(latest_job_row), enrichment

    def create_enrichment_job(
        self,
        news_id: str,
        *,
        max_attempts: int = 3,
    ) -> EnrichmentJobRecord:
        now = _utc_datetime()
        job_id = str(uuid4())
        with connect_postgres(self.dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO enrichment_jobs (
                        job_id,
                        news_id,
                        status,
                        attempts,
                        max_attempts,
                        last_error,
                        last_analysis_status,
                        created_at,
                        updated_at,
                        next_retry_at,
                        started_at,
                        completed_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                    """,
                    (
                        job_id,
                        news_id,
                        EnrichmentJobStatus.QUEUED.value,
                        0,
                        max_attempts,
                        None,
                        None,
                        now,
                        now,
                        None,
                        None,
                        None,
                    ),
                )
                row = cursor.fetchone()
        job = _job_from_row(row)
        if job is None:
            raise RuntimeError("Failed to create enrichment job record.")
        return job

    def claim_next_enrichment_job(self) -> EnrichmentJobRecord | None:
        with connect_postgres(self.dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM enrichment_jobs
                    WHERE (
                        status = %s
                    ) OR (
                        status = %s
                        AND next_retry_at IS NOT NULL
                        AND next_retry_at <= %s
                    )
                    ORDER BY
                        CASE
                            WHEN status = %s THEN updated_at
                            ELSE next_retry_at
                        END ASC,
                        created_at ASC
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                    """,
                    (
                        EnrichmentJobStatus.QUEUED.value,
                        EnrichmentJobStatus.RETRY_PENDING.value,
                        _utc_datetime(),
                        EnrichmentJobStatus.QUEUED.value,
                    ),
                )
                row = cursor.fetchone()
                if row is None:
                    return None

                now = _utc_datetime()
                cursor.execute(
                    """
                    UPDATE enrichment_jobs
                    SET status = %s,
                        attempts = attempts + 1,
                        updated_at = %s,
                        next_retry_at = %s,
                        started_at = %s
                    WHERE job_id = %s
                    RETURNING *
                    """,
                    (
                        EnrichmentJobStatus.PROCESSING.value,
                        now,
                        None,
                        now,
                        row["job_id"],
                    ),
                )
                claimed_row = cursor.fetchone()
        return _job_from_row(claimed_row)

    def mark_job_completed(
        self,
        job_id: str,
        *,
        analysis_status: AnalysisStatus,
    ) -> EnrichmentJobRecord | None:
        return self._update_job_terminal_state(
            job_id=job_id,
            status=EnrichmentJobStatus.COMPLETED,
            error_message=None,
            analysis_status=analysis_status,
        )

    def mark_job_failed(
        self,
        job_id: str,
        *,
        error_message: str,
        analysis_status: AnalysisStatus | None = None,
    ) -> EnrichmentJobRecord | None:
        return self._update_job_terminal_state(
            job_id=job_id,
            status=EnrichmentJobStatus.FAILED,
            error_message=error_message,
            analysis_status=analysis_status,
        )

    def requeue_job(
        self,
        job_id: str,
        *,
        error_message: str,
        next_retry_at: datetime,
        analysis_status: AnalysisStatus | None = None,
    ) -> EnrichmentJobRecord | None:
        with connect_postgres(self.dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE enrichment_jobs
                    SET status = %s,
                        updated_at = %s,
                        next_retry_at = %s,
                        completed_at = %s,
                        last_error = %s,
                        last_analysis_status = %s
                    WHERE job_id = %s
                    RETURNING *
                    """,
                    (
                        EnrichmentJobStatus.RETRY_PENDING.value,
                        _utc_datetime(),
                        next_retry_at,
                        None,
                        error_message,
                        analysis_status.value if analysis_status is not None else None,
                        job_id,
                    ),
                )
                row = cursor.fetchone()
        return _job_from_row(row)

    def get_enrichment_result(self, news_id: str) -> EnrichmentStoragePayload | None:
        with connect_postgres(self.dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT payload_json
                    FROM enrichment_results
                    WHERE news_id = %s
                    """,
                    (news_id,),
                )
                row = cursor.fetchone()
        if row is None:
            return None
        return _payload_from_storage(row["payload_json"])

    def save_enrichment_result(self, payload: SaveEnrichmentRequest) -> None:
        from psycopg.types.json import Jsonb

        self.upsert_raw_news(payload.raw_news)
        now = _utc_datetime()
        with connect_postgres(self.dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO enrichment_results (
                        news_id,
                        title,
                        link,
                        payload_json,
                        analysis_status,
                        analysis_outcome,
                        analyzed_at,
                        updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(news_id) DO UPDATE SET
                        title = EXCLUDED.title,
                        link = EXCLUDED.link,
                        payload_json = EXCLUDED.payload_json,
                        analysis_status = EXCLUDED.analysis_status,
                        analysis_outcome = EXCLUDED.analysis_outcome,
                        analyzed_at = EXCLUDED.analyzed_at,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        payload.enrichment.news_id,
                        payload.enrichment.title,
                        str(payload.enrichment.link),
                        Jsonb(payload.enrichment.model_dump(mode="json")),
                        payload.enrichment.analysis_status.value,
                        payload.enrichment.analysis_outcome.value,
                        payload.enrichment.analyzed_at,
                        now,
                    ),
                )

    def list_recent_ticker_sentiments(self, ticker: str) -> list[TickerSentimentObservation]:
        normalized_ticker = ticker.strip().upper()
        with connect_postgres(self.dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT er.payload_json
                    FROM enrichment_results er
                    INNER JOIN raw_news_tickers rnt
                        ON rnt.news_id = er.news_id
                    WHERE rnt.ticker = %s
                    ORDER BY er.analyzed_at DESC
                    LIMIT 50
                    """,
                    (normalized_ticker,),
                )
                rows = cursor.fetchall()

        observations: list[TickerSentimentObservation] = []
        for row in rows:
            payload = _payload_from_storage(row["payload_json"])
            if payload.sentiment is None:
                continue
            observations.append(
                TickerSentimentObservation(
                    ticker=normalized_ticker,
                    news_id=payload.news_id,
                    score=payload.sentiment.score,
                    label=payload.sentiment.label,
                    confidence=payload.sentiment.confidence,
                    analyzed_at=payload.analyzed_at,
                )
            )
        return observations

    def get_operational_stats(self) -> OperationalStatsResponse:
        with connect_postgres(self.dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT payload_json
                    FROM enrichment_results
                    """
                )
                enrichment_rows = cursor.fetchall()
                cursor.execute(
                    """
                    SELECT *
                    FROM enrichment_jobs
                    """
                )
                job_rows = cursor.fetchall()

        enrichments = [_payload_from_storage(row["payload_json"]) for row in enrichment_rows]
        jobs = [_job_from_row(row) for row in job_rows]
        return _build_operational_stats(
            enrichments=enrichments,
            jobs=[job for job in jobs if job is not None],
        )

    def _update_job_terminal_state(
        self,
        *,
        job_id: str,
        status: EnrichmentJobStatus,
        error_message: str | None,
        analysis_status: AnalysisStatus | None,
    ) -> EnrichmentJobRecord | None:
        now = _utc_datetime()
        with connect_postgres(self.dsn) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE enrichment_jobs
                    SET status = %s,
                        updated_at = %s,
                        completed_at = %s,
                        next_retry_at = %s,
                        last_error = %s,
                        last_analysis_status = %s
                    WHERE job_id = %s
                    RETURNING *
                    """,
                    (
                        status.value,
                        now,
                        now,
                        None,
                        error_message,
                        analysis_status.value if analysis_status is not None else None,
                        job_id,
                    ),
                )
                row = cursor.fetchone()
        return _job_from_row(row)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utc_datetime() -> datetime:
    return datetime.now(timezone.utc)


def _datetime_to_storage(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _payload_from_storage(value) -> EnrichmentStoragePayload:
    if isinstance(value, str):
        return EnrichmentStoragePayload.model_validate_json(value)
    return EnrichmentStoragePayload.model_validate(value)


def _job_from_row(row) -> EnrichmentJobRecord | None:
    if row is None:
        return None
    return EnrichmentJobRecord(
        job_id=row["job_id"],
        news_id=row["news_id"],
        status=row["status"],
        attempts=row["attempts"],
        max_attempts=row["max_attempts"],
        last_error=row["last_error"],
        last_analysis_status=row["last_analysis_status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        next_retry_at=row["next_retry_at"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
    )


def _build_operational_stats(
    *,
    enrichments: list[EnrichmentStoragePayload],
    jobs: list[EnrichmentJobRecord],
) -> OperationalStatsResponse:
    total_fetch_failures = 0
    retryable_fetch_failures = 0
    analysis_status_counts: dict[str, int] = {}
    extraction_source_counts: dict[str, int] = {}
    fetch_failure_category_counts: dict[str, int] = {}
    domain_failure_counts: dict[str, tuple[int, int]] = {}
    domain_outcome_counts: dict[str, tuple[int, int, int, int, int]] = {}
    job_status_counts: dict[str, int] = {}
    summarize_failed_count = 0
    timeout_failure_count = 0
    gemini_rate_limited_count = 0
    cleaned_to_raw_ratios: list[float] = []
    low_preservation_count = 0

    for job in jobs:
        job_status_counts[job.status.value] = job_status_counts.get(job.status.value, 0) + 1

    for enrichment in enrichments:
        analysis_key = enrichment.analysis_status.value
        analysis_status_counts[analysis_key] = analysis_status_counts.get(analysis_key, 0) + 1
        if enrichment.analysis_status == AnalysisStatus.SUMMARIZE_FAILED:
            summarize_failed_count += 1
        elif enrichment.failure_code == "summary_generation_failed":
            summarize_failed_count += 1

        fetch_result = enrichment.fetch_result
        if fetch_result is not None:
            raw_length = len(fetch_result.raw_text or "")
            if raw_length > 0:
                ratio = enrichment.cleaned_text_char_count / raw_length
                cleaned_to_raw_ratios.append(ratio)
                if ratio < 0.30:
                    low_preservation_count += 1
        if fetch_result is not None and fetch_result.extraction_source is not None:
            extraction_key = fetch_result.extraction_source.value
            extraction_source_counts[extraction_key] = (
                extraction_source_counts.get(extraction_key, 0) + 1
            )

        joined_errors = " ".join(error.message.lower() for error in enrichment.errors)
        if "timed out" in joined_errors or "timeout" in joined_errors:
            timeout_failure_count += 1
        if "rate limit" in joined_errors or "429" in joined_errors:
            gemini_rate_limited_count += 1

        domain_key = (
            fetch_result.publisher_domain
            if fetch_result is not None and fetch_result.publisher_domain
            else "unknown"
        )
        total_count, success_count, partial_count, filtered_count, fatal_count = domain_outcome_counts.get(
            domain_key,
            (0, 0, 0, 0, 0),
        )
        domain_outcome_counts[domain_key] = (
            total_count + 1,
            success_count + (1 if enrichment.analysis_outcome == AnalysisOutcome.SUCCESS else 0),
            partial_count + (
                1 if enrichment.analysis_outcome == AnalysisOutcome.PARTIAL_SUCCESS else 0
            ),
            filtered_count + (
                1 if enrichment.analysis_outcome == AnalysisOutcome.FILTERED else 0
            ),
            fatal_count + (1 if enrichment.analysis_outcome == AnalysisOutcome.FATAL_FAILURE else 0),
        )

        if fetch_result is None or enrichment.analysis_status != AnalysisStatus.FETCH_FAILED:
            continue

        total_fetch_failures += 1
        if fetch_result.retryable:
            retryable_fetch_failures += 1

        if fetch_result.failure_category is not None:
            category_key = fetch_result.failure_category.value
            fetch_failure_category_counts[category_key] = (
                fetch_failure_category_counts.get(category_key, 0) + 1
            )

        domain_key = fetch_result.publisher_domain or "unknown"
        current_failure_count, current_retryable_count = domain_failure_counts.get(
            domain_key,
            (0, 0),
        )
        domain_failure_counts[domain_key] = (
            current_failure_count + 1,
            current_retryable_count + (1 if fetch_result.retryable else 0),
        )

    total_results = len(enrichments)
    average_ratio = (
        sum(cleaned_to_raw_ratios) / len(cleaned_to_raw_ratios)
        if cleaned_to_raw_ratios
        else None
    )
    return OperationalStatsResponse(
        total_enrichment_results=len(enrichments),
        total_jobs=len(jobs),
        total_fetch_failures=total_fetch_failures,
        retryable_fetch_failures=retryable_fetch_failures,
        summarize_failed_count=summarize_failed_count,
        timeout_failure_count=timeout_failure_count,
        gemini_rate_limited_count=gemini_rate_limited_count,
        summarize_failed_ratio=(
            summarize_failed_count / total_results if total_results else 0.0
        ),
        timeout_failure_ratio=(
            timeout_failure_count / total_results if total_results else 0.0
        ),
        gemini_rate_limited_ratio=(
            gemini_rate_limited_count / total_results if total_results else 0.0
        ),
        average_cleaned_to_raw_ratio=average_ratio,
        low_preservation_count=low_preservation_count,
        job_status_counts=_sorted_count_metrics(job_status_counts),
        analysis_status_counts=_sorted_count_metrics(analysis_status_counts),
        extraction_source_counts=_sorted_count_metrics(extraction_source_counts),
        fetch_failure_category_counts=_sorted_count_metrics(fetch_failure_category_counts),
        top_failure_domains=_sorted_domain_metrics(domain_failure_counts),
        publisher_outcomes=_sorted_outcome_metrics(domain_outcome_counts),
    )


def _build_raw_news_request(
    *,
    news_id: str,
    title: str,
    link: str,
    ticker: list[str] | None,
    source: str | None,
    published_at,
    article_text: str | None,
    summary_text: str | None,
) -> ArticleEnrichmentRequest:
    article_text = normalize_optional_text_input(article_text)
    summary_text = normalize_optional_text_input(summary_text)
    if article_text or summary_text:
        return RawNewsIngestionRequest(
            news_id=news_id,
            title=title,
            link=link,
            ticker=ticker,
            source=source,
            published_at=published_at,
            article_text=article_text,
            summary_text=summary_text,
        )

    return ArticleEnrichmentRequest(
        news_id=news_id,
        title=title,
        link=link,
        ticker=ticker,
        source=source,
        published_at=published_at,
    )


def _sorted_count_metrics(counts: dict[str, int]) -> list[CountMetric]:
    return [
        CountMetric(key=key, count=count)
        for key, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _sorted_domain_metrics(
    counts: dict[str, tuple[int, int]]
) -> list[PublisherFetchFailureMetric]:
    return [
        PublisherFetchFailureMetric(
            publisher_domain=domain,
            failure_count=failure_count,
            retryable_failure_count=retryable_failure_count,
        )
        for domain, (failure_count, retryable_failure_count) in sorted(
            counts.items(),
            key=lambda item: (-item[1][0], item[0]),
        )[:10]
    ]


def _sorted_outcome_metrics(
    counts: dict[str, tuple[int, int, int, int, int]]
) -> list[PublisherOutcomeMetric]:
    return [
        PublisherOutcomeMetric(
            publisher_domain=domain,
            total_count=total_count,
            success_count=success_count,
            partial_success_count=partial_success_count,
            filtered_count=filtered_count,
            fatal_failure_count=fatal_failure_count,
        )
        for domain, (
            total_count,
            success_count,
            partial_success_count,
            filtered_count,
            fatal_failure_count,
        ) in sorted(
            counts.items(),
            key=lambda item: (-item[1][0], item[0]),
        )[:10]
    ]