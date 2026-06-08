from __future__ import annotations

import base64
import secrets
from typing import Final

from fastapi import Request
from fastapi.responses import Response

from app.core.config import get_settings


_BASIC_AUTH_REALM: Final[str] = 'Basic realm="Financial News Gen AI Service"'
_EXEMPT_PATHS: Final[tuple[str, ...]] = ("/health",)
_LOCAL_PROBE_HOSTS: Final[frozenset[str]] = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})


def _is_internal_root_probe(request: Request) -> bool:
    """Allow Render-style local HEAD probes to pass without weakening user-facing auth."""
    client_host = request.client.host if request.client else None
    return request.method == "HEAD" and request.url.path == "/" and client_host in _LOCAL_PROBE_HOSTS


def basic_auth_required(request: Request) -> bool:
    """Return whether the current request should be protected by Basic Auth."""
    settings = get_settings()
    if not settings.basic_auth_enabled:
        return False
    return request.url.path not in _EXEMPT_PATHS and not _is_internal_root_probe(request)


def unauthorized_basic_auth_response() -> Response:
    """Return a 401 response that prompts the browser's Basic Auth dialog."""
    return Response(
        content="Authentication required.",
        status_code=401,
        headers={"WWW-Authenticate": _BASIC_AUTH_REALM},
    )


def is_basic_auth_authorized(request: Request) -> bool:
    """Validate the incoming Authorization header against configured credentials."""
    settings = get_settings()
    if not settings.basic_auth_enabled:
        return True

    authorization = request.headers.get("Authorization")
    if not authorization:
        return False

    scheme, _, encoded_credentials = authorization.partition(" ")
    if scheme.lower() != "basic" or not encoded_credentials:
        return False

    try:
        decoded = base64.b64decode(encoded_credentials).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return False

    username, separator, password = decoded.partition(":")
    if not separator:
        return False

    return secrets.compare_digest(username, settings.basic_auth_user or "") and secrets.compare_digest(
        password,
        settings.basic_auth_password or "",
    )