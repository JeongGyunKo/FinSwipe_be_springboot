from __future__ import annotations

import json
import logging
from datetime import datetime


DEFAULT_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
DEFAULT_LOG_LEVEL = logging.INFO


def configure_logging(level: int = DEFAULT_LOG_LEVEL) -> None:
    """Configure a minimal application-wide logging format once."""
    root_logger = logging.getLogger()
    if root_logger.handlers:
        return
    logging.basicConfig(level=level, format=DEFAULT_LOG_FORMAT)


def get_logger(name: str) -> logging.Logger:
    """Return a standard library logger for the given module."""
    return logging.getLogger(name)


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    **fields: object,
) -> None:
    """Emit a structured, readable key-value log message."""
    logger.log(level, _format_message(event=event, fields=fields))


def _format_message(*, event: str, fields: dict[str, object]) -> str:
    parts = [f"event={event}"]
    for key, value in fields.items():
        if value is None:
            continue
        parts.append(f"{key}={_serialize(value)}")
    return " ".join(parts)


def _serialize(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))