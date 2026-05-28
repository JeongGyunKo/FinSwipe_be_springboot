from __future__ import annotations

import base64

from fastapi.testclient import TestClient

from app.main import app


def _basic_auth_header(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return {"Authorization": f"Basic {token}"}


def test_basic_auth_is_not_required_by_default(monkeypatch) -> None:
    monkeypatch.delenv("BASIC_AUTH_USER", raising=False)
    monkeypatch.delenv("BASIC_AUTH_PASSWORD", raising=False)

    client = TestClient(app)
    response = client.get("/")

    assert response.status_code == 200


def test_basic_auth_protects_root_and_docs_but_not_health(monkeypatch) -> None:
    monkeypatch.setenv("BASIC_AUTH_USER", "teammate")
    monkeypatch.setenv("BASIC_AUTH_PASSWORD", "temporary-pass")

    client = TestClient(app)

    root_response = client.get("/")
    docs_response = client.get("/docs")
    health_response = client.get("/health")
    deep_health_response = client.get("/health/deep")

    assert root_response.status_code == 401
    assert docs_response.status_code == 401
    assert health_response.status_code == 200
    assert health_response.json()["status"] == "ok"
    assert deep_health_response.status_code == 200
    assert deep_health_response.json()["status"] in {"ok", "degraded"}


def test_basic_auth_accepts_valid_credentials(monkeypatch) -> None:
    monkeypatch.setenv("BASIC_AUTH_USER", "teammate")
    monkeypatch.setenv("BASIC_AUTH_PASSWORD", "temporary-pass")

    client = TestClient(app)
    response = client.get("/", headers=_basic_auth_header("teammate", "temporary-pass"))

    assert response.status_code == 200


def test_basic_auth_allows_internal_head_probe_but_keeps_get_protected(monkeypatch) -> None:
    monkeypatch.setenv("BASIC_AUTH_USER", "teammate")
    monkeypatch.setenv("BASIC_AUTH_PASSWORD", "temporary-pass")

    client = TestClient(app)
    head_response = client.head("/")
    get_response = client.get("/")

    assert head_response.status_code == 200
    assert get_response.status_code == 401