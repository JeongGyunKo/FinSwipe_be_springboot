from __future__ import annotations

import requests

from app.services.gemini.client import (
    _build_generate_content_url,
    _extract_retry_after_seconds,
    gemini_generate_content,
    gemini_log_context,
)


def test_build_generate_content_url_uses_direct_gemini_rest_endpoint() -> None:
    assert (
        _build_generate_content_url(
            "https://generativelanguage.googleapis.com/v1beta",
            "gemini-2.5-flash-lite",
        )
        == "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent"
    )


def test_extract_retry_after_seconds_from_rate_limit_message() -> None:
    class _Response:
        headers = {}

        def json(self) -> dict[str, object]:
            return {
                "error": {
                    "message": "Rate limit reached. Please try again in 3.76s."
                }
            }

    assert _extract_retry_after_seconds(_Response()) == 3.76


def test_gemini_generate_content_retries_once_after_short_429(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_API_BASE_URL", "https://generativelanguage.googleapis.com/v1beta")
    monkeypatch.setenv("GEMINI_RETRY_AFTER_MAX_SECONDS", "2")

    calls = {"count": 0}
    sleep_calls: list[float] = []

    class _Response:
        def __init__(self, status_code: int, payload: dict[str, object]) -> None:
            self.status_code = status_code
            self._payload = payload
            self.headers = {}

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise requests.HTTPError("boom", response=self)

        def json(self) -> dict[str, object]:
            return self._payload

    def _fake_post(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return _Response(
                429,
                {"error": {"message": "Rate limit reached. Please try again in 1.25s."}},
            )
        return _Response(
            200,
            {
                "candidates": [{"content": {"parts": [{"text": "ok"}]}}],
                "usageMetadata": {
                    "promptTokenCount": 10,
                    "candidatesTokenCount": 2,
                    "totalTokenCount": 12,
                },
            },
        )

    monkeypatch.setattr("app.services.gemini.client.requests.post", _fake_post)
    monkeypatch.setattr(
        "app.services.gemini.client.time.sleep",
        lambda seconds: sleep_calls.append(seconds),
    )

    result = gemini_generate_content(
        model="gemini-2.5-flash-lite",
        system_prompt="system",
        user_prompt="user",
        request_label="test_retry",
    )

    assert result == "ok"
    assert calls["count"] == 2
    assert sleep_calls == [1.25]


def test_gemini_generate_content_does_not_sleep_on_long_rate_limit(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_API_BASE_URL", "https://generativelanguage.googleapis.com/v1beta")
    monkeypatch.setenv("GEMINI_RETRY_AFTER_MAX_SECONDS", "0")

    calls = {"count": 0}
    sleep_calls: list[float] = []

    class _Response:
        status_code = 429
        headers = {}

        def raise_for_status(self) -> None:
            raise requests.HTTPError("rate limit", response=self)

        def json(self) -> dict[str, object]:
            return {
                "error": {
                    "message": "Resource exhausted. Please try again in 52.18s."
                }
            }

    def _fake_post(*args, **kwargs):
        calls["count"] += 1
        return _Response()

    monkeypatch.setattr("app.services.gemini.client.requests.post", _fake_post)
    monkeypatch.setattr(
        "app.services.gemini.client.time.sleep",
        lambda seconds: sleep_calls.append(seconds),
    )

    try:
        gemini_generate_content(
            model="gemini-2.5-flash-lite",
            system_prompt="system",
            user_prompt="user",
            request_label="test_rate_limit",
        )
    except requests.HTTPError:
        pass
    else:
        raise AssertionError("Expected rate limit to fail fast.")

    assert calls["count"] == 1
    assert sleep_calls == []


def test_gemini_logs_include_news_context_and_token_usage(monkeypatch, caplog) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_API_BASE_URL", "https://generativelanguage.googleapis.com/v1beta")

    class _Response:
        status_code = 200
        headers = {}

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "candidates": [{"content": {"parts": [{"text": "ok"}]}}],
                "usageMetadata": {
                    "promptTokenCount": 10,
                    "candidatesTokenCount": 2,
                    "totalTokenCount": 12,
                },
            }

    monkeypatch.setattr(
        "app.services.gemini.client.requests.post",
        lambda *args, **kwargs: _Response(),
    )

    with caplog.at_level("INFO"), gemini_log_context(
        news_id="news-123",
        link="https://example.com/article",
        gemini_context="unit_test",
    ):
        result = gemini_generate_content(
            model="gemini-2.5-flash-lite",
            system_prompt="system",
            user_prompt="user",
            request_label="summary_generation",
        )

    assert result == "ok"
    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert "event=gemini_request_started" in messages
    assert "event=gemini_request_completed" in messages
    assert 'news_id="news-123"' in messages
    assert 'request_label="summary_generation"' in messages
    assert "total_tokens=12" in messages