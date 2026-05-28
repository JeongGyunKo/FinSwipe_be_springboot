"""Explainability utilities for financial news sentiment analysis."""

from app.core import get_settings


def is_xai_backend_disabled() -> bool:
    return get_settings().xai_backend == "disabled"


def explain_sentiment(*args, **kwargs):
    backend = get_settings().xai_backend
    if backend == "attention":
        from app.services.xai.attention_explainer import (
            explain_sentiment as _explain_sentiment,
        )
    elif backend == "disabled":
        raise RuntimeError("XAI backend is disabled.")
    else:
        raise ValueError(f"Unsupported XAI backend: {backend}")

    return _explain_sentiment(*args, **kwargs)

__all__ = ["explain_sentiment", "is_xai_backend_disabled"]