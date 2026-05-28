from __future__ import annotations

from app.core.config import get_settings


def test_inline_xai_is_enabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("GENAI_ENABLE_INLINE_XAI", raising=False)

    assert get_settings().enable_inline_xai is True


def test_inline_xai_can_be_disabled_by_env(monkeypatch) -> None:
    monkeypatch.setenv("GENAI_ENABLE_INLINE_XAI", "false")

    assert get_settings().enable_inline_xai is False


def test_zeabur_defaults_to_worker_backed_direct_enrichment(monkeypatch) -> None:
    monkeypatch.delenv("GENAI_USE_WORKER_FOR_DIRECT_ENRICHMENT", raising=False)
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.setenv("ZEABUR_SERVICE_ID", "svc-test")

    assert get_settings().use_worker_backed_direct_enrichment is True