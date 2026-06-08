from __future__ import annotations

import os


DEFAULT_POSTGRES_CONNECT_TIMEOUT_SECONDS = 3


def get_postgres_dsn() -> str | None:
    """Return the configured Postgres DSN when one is available."""
    return os.getenv("GENAI_POSTGRES_DSN") or os.getenv("DATABASE_URL")


def initialize_postgres_database(dsn: str | None = None) -> str:
    """Ensure the Postgres schema exists for the enrichment service."""
    resolved_dsn = dsn or get_postgres_dsn()
    if not resolved_dsn:
        raise RuntimeError(
            "Postgres backend selected but no DSN was configured. "
            "Set GENAI_POSTGRES_DSN or DATABASE_URL."
        )

    import psycopg

    with psycopg.connect(
        resolved_dsn,
        autocommit=True,
        connect_timeout=DEFAULT_POSTGRES_CONNECT_TIMEOUT_SECONDS,
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS raw_news (
                    news_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    link TEXT NOT NULL,
                    source TEXT,
                    published_at TIMESTAMPTZ,
                    provided_article_text TEXT,
                    provided_summary_text TEXT,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            cursor.execute(
                """
                ALTER TABLE raw_news
                ADD COLUMN IF NOT EXISTS provided_article_text TEXT
                """
            )
            cursor.execute(
                """
                ALTER TABLE raw_news
                ADD COLUMN IF NOT EXISTS provided_summary_text TEXT
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS raw_news_tickers (
                    news_id TEXT NOT NULL REFERENCES raw_news(news_id) ON DELETE CASCADE,
                    ticker TEXT NOT NULL,
                    PRIMARY KEY (news_id, ticker)
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS enrichment_results (
                    news_id TEXT PRIMARY KEY REFERENCES raw_news(news_id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    link TEXT NOT NULL,
                    payload_json JSONB NOT NULL,
                    analysis_status TEXT NOT NULL,
                    analysis_outcome TEXT NOT NULL,
                    analyzed_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS enrichment_jobs (
                    job_id TEXT PRIMARY KEY,
                    news_id TEXT NOT NULL REFERENCES raw_news(news_id) ON DELETE CASCADE,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 3,
                    last_error TEXT,
                    last_analysis_status TEXT,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL,
                    next_retry_at TIMESTAMPTZ,
                    started_at TIMESTAMPTZ,
                    completed_at TIMESTAMPTZ
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_enrichment_jobs_status_created_at
                ON enrichment_jobs(status, created_at)
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_enrichment_jobs_status_next_retry_at
                ON enrichment_jobs(status, next_retry_at)
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_raw_news_tickers_ticker
                ON raw_news_tickers(ticker)
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_enrichment_results_analyzed_at
                ON enrichment_results(analyzed_at)
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS digest_cache (
                    ticker TEXT NOT NULL,
                    level INT NOT NULL,
                    tendency TEXT NOT NULL,
                    digest_json JSONB NOT NULL,
                    generated_at TIMESTAMPTZ NOT NULL,
                    PRIMARY KEY (ticker, level, tendency)
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_digest_cache_generated_at
                ON digest_cache(ticker, generated_at)
                """
            )

    return resolved_dsn


def connect_postgres(dsn: str | None = None):
    """Open a Postgres connection configured for dict-like row access."""
    resolved_dsn = dsn or get_postgres_dsn()
    if not resolved_dsn:
        raise RuntimeError(
            "Postgres backend selected but no DSN was configured. "
            "Set GENAI_POSTGRES_DSN or DATABASE_URL."
        )

    import psycopg
    from psycopg.rows import dict_row

    return psycopg.connect(
        resolved_dsn,
        row_factory=dict_row,
        connect_timeout=DEFAULT_POSTGRES_CONNECT_TIMEOUT_SECONDS,
    )


def ping_postgres(dsn: str | None = None) -> tuple[bool, str | None]:
    """Return whether the configured Postgres database is reachable."""
    resolved_dsn = dsn or get_postgres_dsn()
    if not resolved_dsn:
        return False, "Postgres DSN is not configured."

    try:
        import psycopg

        with psycopg.connect(
            resolved_dsn,
            autocommit=True,
            connect_timeout=DEFAULT_POSTGRES_CONNECT_TIMEOUT_SECONDS,
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
    except Exception as exc:
        return False, str(exc)

    return True, None