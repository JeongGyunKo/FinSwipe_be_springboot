from __future__ import annotations

import app.repositories as repository_module


def test_create_repository_defaults_to_sqlite(monkeypatch) -> None:
    monkeypatch.delenv("GENAI_DATABASE_BACKEND", raising=False)
    monkeypatch.delenv("DATABASE_BACKEND", raising=False)
    monkeypatch.setattr(repository_module, "initialize_database_backend", lambda: None)

    class FakeSQLiteRepository:
        pass

    monkeypatch.setattr(repository_module, "SQLiteEnrichmentRepository", FakeSQLiteRepository)

    repository = repository_module.create_repository()

    assert isinstance(repository, FakeSQLiteRepository)


def test_create_repository_uses_postgres_when_configured(monkeypatch) -> None:
    monkeypatch.setenv("GENAI_DATABASE_BACKEND", "postgres")
    monkeypatch.setenv("GENAI_POSTGRES_DSN", "postgresql://user:pass@localhost:5432/genai")
    monkeypatch.setattr(repository_module, "initialize_database_backend", lambda: None)

    class FakePostgresRepository:
        def __init__(self, dsn: str) -> None:
            self.dsn = dsn

    monkeypatch.setattr(repository_module, "PostgresEnrichmentRepository", FakePostgresRepository)

    repository = repository_module.create_repository()

    assert isinstance(repository, FakePostgresRepository)
    assert repository.dsn == "postgresql://user:pass@localhost:5432/genai"


def test_create_repository_requires_dsn_for_postgres(monkeypatch) -> None:
    monkeypatch.setenv("GENAI_DATABASE_BACKEND", "postgres")
    monkeypatch.delenv("GENAI_POSTGRES_DSN", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(repository_module, "initialize_database_backend", lambda: None)

    try:
        repository_module.create_repository()
    except RuntimeError as exc:
        assert "GENAI_POSTGRES_DSN" in str(exc)
    else:
        raise AssertionError("Expected create_repository() to fail without a Postgres DSN.")