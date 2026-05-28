"""Persistence boundary for raw news metadata and AI enrichment results."""

from __future__ import annotations

from app.db import get_database_backend, get_postgres_dsn, initialize_database_backend
from app.repositories.enrichment_repository import (
    EnrichmentRepository,
    InMemoryEnrichmentRepository,
    PostgresEnrichmentRepository,
    SaveEnrichmentRequest,
    SQLiteEnrichmentRepository,
)


def create_repository() -> EnrichmentRepository:
    """Build the configured repository implementation for the current environment."""
    backend = get_database_backend()
    initialize_database_backend()
    if backend in {"postgres", "postgresql"}:
        dsn = get_postgres_dsn()
        if not dsn:
            raise RuntimeError(
                "Postgres backend selected but no DSN was configured. "
                "Set GENAI_POSTGRES_DSN or DATABASE_URL."
            )
        return PostgresEnrichmentRepository(dsn=dsn)
    if backend != "sqlite":
        raise RuntimeError(f"Unsupported database backend: {backend}")
    return SQLiteEnrichmentRepository()


__all__ = [
    "create_repository",
    "EnrichmentRepository",
    "InMemoryEnrichmentRepository",
    "PostgresEnrichmentRepository",
    "SaveEnrichmentRequest",
    "SQLiteEnrichmentRepository",
]