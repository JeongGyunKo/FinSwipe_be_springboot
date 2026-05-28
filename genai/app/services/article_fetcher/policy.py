from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final
from urllib.error import URLError

import requests


DEFAULT_RETRYABLE_HTTP_STATUS_CODES: Final[frozenset[int]] = frozenset(
    {408, 409, 425, 429, 500, 502, 503, 504}
)
DEFAULT_BLOCKED_HTTP_STATUS_CODES: Final[frozenset[int]] = frozenset({401, 403})
DEFAULT_NETWORK_RETRY_HINTS: Final[tuple[str, ...]] = (
    "timed out",
    "temporary failure",
    "connection reset",
    "connection aborted",
    "connection refused",
    "remote end closed connection",
    "name or service not known",
    "nodename nor servname provided",
    "ssl certificate verification failed",
    "tlsv1 alert",
)


@dataclass(frozen=True, slots=True)
class FetchRetryPolicy:
    """Central policy describing when article fetch attempts should be retried."""

    max_retries: int = 2
    base_backoff_seconds: float = 0.4
    max_backoff_seconds: float = 2.0
    retryable_http_status_codes: frozenset[int] = field(
        default_factory=lambda: DEFAULT_RETRYABLE_HTTP_STATUS_CODES
    )
    blocked_http_status_codes: frozenset[int] = field(
        default_factory=lambda: DEFAULT_BLOCKED_HTTP_STATUS_CODES
    )
    network_retry_hints: tuple[str, ...] = field(
        default_factory=lambda: DEFAULT_NETWORK_RETRY_HINTS
    )

    def should_retry(self, error: Exception, *, attempt_index: int) -> bool:
        """Return whether the given error should trigger another fetch attempt."""
        if attempt_index >= self.max_retries:
            return False

        if isinstance(error, requests.HTTPError):
            status_code = error.response.status_code if error.response is not None else None
            return status_code in self.retryable_http_status_codes

        if isinstance(error, URLError):
            reason_text = str(getattr(error, "reason", error)).lower()
            return any(hint in reason_text for hint in self.network_retry_hints)

        if isinstance(error, requests.RequestException):
            reason_text = str(error).lower()
            return any(hint in reason_text for hint in self.network_retry_hints)

        return False

    def is_access_block(self, error: Exception) -> bool:
        """Return whether the error likely indicates publisher access blocking."""
        if not isinstance(error, requests.HTTPError) or error.response is None:
            return False
        return error.response.status_code in self.blocked_http_status_codes

    def is_rate_limited(self, error: Exception) -> bool:
        """Return whether the error likely indicates remote rate limiting."""
        if not isinstance(error, requests.HTTPError) or error.response is None:
            return False
        return error.response.status_code == 429

    def backoff_seconds(self, attempt_index: int) -> float:
        """Return a bounded linear backoff interval for the retry attempt."""
        delay = self.base_backoff_seconds * (attempt_index + 1)
        return min(delay, self.max_backoff_seconds)