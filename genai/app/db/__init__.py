"""Database helpers for the enrichment service."""

from __future__ import annotations

import os
import threading

from app.db.postgres import (
    connect_postgres,
    get_postgres_dsn,
    initialize_postgres_database,
    ping_postgres,
)
from app.db.sqlite import connect_sqlite, get_default_db_path, initialize_sqlite_database, ping_sqlite


_INITIALIZATION_LOCK = threading.Lock()
_INITIALIZED_BACKENDS: set[str] = set()


def get_database_backend() -> str:
    """Return the configured storage backend name."""
    return (os.getenv("GENAI_DATABASE_BACKEND") or os.getenv("DATABASE_BACKEND") or "sqlite").lower()


def initialize_database_backend() -> None:
    """Initialize the configured database backend schema."""
    backend = get_database_backend()
    if backend in _INITIALIZED_BACKENDS:
        return

    with _INITIALIZATION_LOCK:
        if backend in _INITIALIZED_BACKENDS:
            return
        if backend in {"postgres", "postgresql"}:
            initialize_postgres_database()
        else:
            initialize_sqlite_database()
        _INITIALIZED_BACKENDS.add(backend)


def ping_database_backend() -> tuple[bool, str | None]:
    """Check whether the configured database backend is reachable."""
    backend = get_database_backend()
    if backend in {"postgres", "postgresql"}:
        return ping_postgres()
    return ping_sqlite()


__all__ = [
    "connect_postgres",
    "connect_sqlite",
    "get_database_backend",
    "get_default_db_path",
    "get_postgres_dsn",
    "initialize_database_backend",
    "initialize_postgres_database",
    "initialize_sqlite_database",
    "ping_database_backend",
    "ping_postgres",
]