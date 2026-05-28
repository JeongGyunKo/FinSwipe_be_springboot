from __future__ import annotations

import os
import sqlite3
from pathlib import Path


DEFAULT_DB_FILENAME = "genai_service.db"


def get_default_db_path() -> Path:
    """Return the configured SQLite path, creating a local data directory if needed."""
    env_path = os.getenv("GENAI_SQLITE_DB_PATH")
    if env_path:
        return Path(env_path).expanduser().resolve()

    project_root = Path(__file__).resolve().parents[2]
    return project_root / "data" / DEFAULT_DB_FILENAME


def initialize_sqlite_database(db_path: Path | None = None) -> Path:
    """Create the SQLite database file and core tables if they do not exist."""
    resolved_path = (db_path or get_default_db_path()).resolve()
    resolved_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(resolved_path) as connection:
        connection.executescript(
            """
            PRAGMA journal_mode = WAL;
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS raw_news (
                news_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                link TEXT NOT NULL,
                source TEXT,
                published_at TEXT,
                provided_article_text TEXT,
                provided_summary_text TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS raw_news_tickers (
                news_id TEXT NOT NULL,
                ticker TEXT NOT NULL,
                PRIMARY KEY (news_id, ticker),
                FOREIGN KEY (news_id) REFERENCES raw_news(news_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS enrichment_results (
                news_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                link TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                analysis_status TEXT NOT NULL,
                analysis_outcome TEXT NOT NULL,
                analyzed_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (news_id) REFERENCES raw_news(news_id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS enrichment_jobs (
                job_id TEXT PRIMARY KEY,
                news_id TEXT NOT NULL,
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 3,
                last_error TEXT,
                last_analysis_status TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                next_retry_at TEXT,
                started_at TEXT,
                completed_at TEXT,
                FOREIGN KEY (news_id) REFERENCES raw_news(news_id) ON DELETE CASCADE
            );

            """
        )
        _ensure_column(
            connection,
            table_name="raw_news",
            column_name="provided_article_text",
            column_sql="TEXT",
        )
        _ensure_column(
            connection,
            table_name="raw_news",
            column_name="provided_summary_text",
            column_sql="TEXT",
        )
        _ensure_column(
            connection,
            table_name="enrichment_jobs",
            column_name="next_retry_at",
            column_sql="TEXT",
        )
        connection.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_enrichment_jobs_status_created_at
            ON enrichment_jobs(status, created_at);

            CREATE INDEX IF NOT EXISTS idx_enrichment_jobs_status_next_retry_at
            ON enrichment_jobs(status, next_retry_at);

            CREATE INDEX IF NOT EXISTS idx_raw_news_tickers_ticker
            ON raw_news_tickers(ticker);

            CREATE INDEX IF NOT EXISTS idx_enrichment_results_analyzed_at
            ON enrichment_results(analyzed_at);
            """
        )

    return resolved_path


def connect_sqlite(db_path: Path | None = None) -> sqlite3.Connection:
    """Open a SQLite connection with row access and foreign keys enabled."""
    resolved_path = initialize_sqlite_database(db_path)
    connection = sqlite3.connect(resolved_path, timeout=30, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def ping_sqlite(db_path: Path | None = None) -> tuple[bool, str | None]:
    """Return whether the configured SQLite database file is reachable."""
    resolved_path = (db_path or get_default_db_path()).resolve()
    resolved_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with sqlite3.connect(resolved_path, timeout=5) as connection:
            connection.execute("SELECT 1").fetchone()
    except Exception as exc:
        return False, str(exc)

    return True, None


def _ensure_column(
    connection: sqlite3.Connection,
    *,
    table_name: str,
    column_name: str,
    column_sql: str,
) -> None:
    existing_columns = {
        row[1]
        for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if column_name in existing_columns:
        return
    connection.execute(
        f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}"
    )