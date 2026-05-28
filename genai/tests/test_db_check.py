from __future__ import annotations

from app.db.check import build_database_status_payload


def test_build_database_status_payload_reports_sqlite(monkeypatch) -> None:
    monkeypatch.setenv("GENAI_DATABASE_BACKEND", "sqlite")
    monkeypatch.delenv("GENAI_POSTGRES_DSN", raising=False)
    monkeypatch.setattr("app.db.check.ping_database_backend", lambda: (True, None))

    payload = build_database_status_payload()

    assert payload["database_backend"] == "sqlite"
    assert payload["database_ok"] is True
    assert payload["database_error"] is None
    assert payload["postgres_dsn_configured"] is False


def test_build_database_status_payload_reports_postgres_config(monkeypatch) -> None:
    monkeypatch.setenv("GENAI_DATABASE_BACKEND", "postgres")
    monkeypatch.setenv("GENAI_POSTGRES_DSN", "postgresql://user:pass@localhost:5432/genai")
    monkeypatch.setattr("app.db.check.ping_database_backend", lambda: (False, "connection refused"))

    payload = build_database_status_payload()

    assert payload["database_backend"] == "postgres"
    assert payload["database_ok"] is False
    assert payload["database_error"] == "connection refused"
    assert payload["postgres_dsn_configured"] is True