from __future__ import annotations

import logging
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from urllib.parse import quote

import threading

import requests

from app.core import get_settings
from app.core.logging import log_event

logger = logging.getLogger(__name__)

# Gemini API 동시 호출 수 제한 — 뉴스분석+퀴즈 합산 최대 5개
_GEMINI_SEMAPHORE = threading.Semaphore(5)

_RETRY_AFTER_PATTERN = re.compile(r"Please try again in ([0-9]+(?:\.[0-9]+)?)s", re.IGNORECASE)
_gemini_log_context: ContextVar[dict[str, object]] = ContextVar(
    "gemini_log_context",
    default={},
)


def gemini_is_enabled() -> bool:
    return bool(get_settings().gemini_api_key)


@contextmanager
def gemini_log_context(**fields: object) -> Iterator[None]:
    """Attach request/job metadata to Gemini logs emitted in this execution context."""
    current = _gemini_log_context.get()
    merged = {**current, **{key: value for key, value in fields.items() if value is not None}}
    token = _gemini_log_context.set(merged)
    try:
        yield
    finally:
        _gemini_log_context.reset(token)


def gemini_generate_content(
    *,
    system_prompt: str,
    user_prompt: str,
    model: str,
    temperature: float = 0.2,
    request_label: str | None = None,
) -> str:
    settings = get_settings()
    if not settings.gemini_api_key:
        raise RuntimeError("Gemini API key is not configured.")

    label = request_label or "unknown"
    url = _build_generate_content_url(settings.gemini_api_base_url, model)
    payload = {
        "system_instruction": {
            "parts": [{"text": system_prompt}],
        },
        "contents": [
            {
                "role": "user",
                "parts": [{"text": user_prompt}],
            }
        ],
        "generationConfig": {
            "temperature": temperature,
        },
    }

    log_event(
        logger,
        logging.INFO,
        "gemini_request_started",
        **_gemini_context_fields(),
        request_label=label,
        model=model,
        system_prompt_chars=len(system_prompt),
        user_prompt_chars=len(user_prompt),
    )

    attempt = 0
    max_attempts = 4
    with _GEMINI_SEMAPHORE:  # 동시 호출 수 제한 (최대 5개)
        while True:
            try:
                response = requests.post(
                    url,
                    headers={
                        "x-goog-api-key": settings.gemini_api_key,
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=settings.gemini_timeout_seconds,
                )
            except requests.Timeout as exc:
                if attempt + 1 < max_attempts:
                    log_event(logger, logging.WARNING, "gemini_timeout_retry",
                              request_label=label, attempt=attempt + 1)
                    time.sleep(3)
                    attempt += 1
                    continue
                raise RuntimeError(f"Gemini API 타임아웃 ({max_attempts}회 재시도 초과)") from exc
            try:
                response.raise_for_status()
                break
            except requests.HTTPError as exc:
                retry_after_seconds = _extract_retry_after_seconds(response)
                error_payload = _safe_json(response)
                error_message = (
                    ((error_payload.get("error") or {}).get("message"))
                    if isinstance(error_payload, dict)
                    else None
                )
                log_event(
                    logger,
                    logging.WARNING,
                    "gemini_request_failed",
                    **_gemini_context_fields(),
                    request_label=label,
                    model=model,
                    status_code=response.status_code,
                    retry_after_seconds=retry_after_seconds,
                    error_message=error_message,
                    attempt=attempt + 1,
                )
                can_retry_rate_limit = (
                    response.status_code == 429
                    and attempt + 1 < max_attempts
                )
                can_retry_server_error = (
                    response.status_code in (500, 502, 503, 529)
                    and attempt + 1 < max_attempts
                )
                if can_retry_rate_limit:
                    wait = retry_after_seconds if (
                        retry_after_seconds is not None
                        and retry_after_seconds <= settings.gemini_retry_after_max_seconds
                    ) else min(10 * (2 ** attempt), 60)
                    log_event(logger, logging.INFO, "gemini_rate_limit_retry",
                              request_label=label, wait_seconds=wait, attempt=attempt + 1)
                    time.sleep(wait)
                    attempt += 1
                    continue
                if can_retry_server_error:
                    time.sleep(3)
                    attempt += 1
                    continue
                raise exc

    data = response.json()
    usage = data.get("usageMetadata") or {}
    log_event(
        logger,
        logging.INFO,
        "gemini_request_completed",
        **_gemini_context_fields(),
        request_label=label,
        model=model,
        prompt_tokens=usage.get("promptTokenCount"),
        completion_tokens=usage.get("candidatesTokenCount"),
        total_tokens=usage.get("totalTokenCount"),
    )
    return _extract_response_text(data)


def _build_generate_content_url(base_url: str, model: str) -> str:
    normalized_base = base_url.rstrip("/")
    normalized_model = model.removeprefix("models/").strip("/")
    return f"{normalized_base}/models/{quote(normalized_model, safe='')}:generateContent"


def _gemini_context_fields() -> dict[str, object]:
    return dict(_gemini_log_context.get())


def _extract_response_text(payload: dict[str, object]) -> str:
    candidates = payload.get("candidates") or []
    if not isinstance(candidates, list) or not candidates:
        raise RuntimeError("Gemini response contained no candidates.")

    candidate = candidates[0]
    if not isinstance(candidate, dict):
        raise RuntimeError("Gemini response candidate was malformed.")
    content = candidate.get("content") or {}
    if not isinstance(content, dict):
        raise RuntimeError("Gemini response content was malformed.")
    parts = content.get("parts") or []
    if not isinstance(parts, list):
        raise RuntimeError("Gemini response parts were malformed.")

    texts = [
        part.get("text", "")
        for part in parts
        if isinstance(part, dict) and isinstance(part.get("text"), str)
    ]
    combined = "\n".join(text.strip() for text in texts if text.strip()).strip()
    if not combined:
        raise RuntimeError("Gemini response contained no text content.")
    return combined


def _extract_retry_after_seconds(response: requests.Response) -> float | None:
    retry_after_header = response.headers.get("Retry-After")
    if retry_after_header:
        try:
            return float(retry_after_header)
        except ValueError:
            pass

    payload = _safe_json(response)
    if isinstance(payload, dict):
        error = payload.get("error") or {}
        message = error.get("message")
        if isinstance(message, str):
            match = _RETRY_AFTER_PATTERN.search(message)
            if match:
                return float(match.group(1))
    return None


def _safe_json(response: requests.Response) -> dict[str, object] | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None