from __future__ import annotations

import os
from dataclasses import dataclass


def _env_flag(name: str, *, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class AppSettings:
    database_backend: str
    postgres_dsn: str | None
    sqlite_path: str | None
    app_host: str
    app_port: int
    worker_poll_interval_seconds: float
    worker_idle_log_interval_seconds: float
    enable_job_process_api: bool
    use_worker_backed_direct_enrichment: bool
    enable_inline_xai: bool
    xai_backend: str
    direct_enrichment_wait_timeout_seconds: float
    direct_enrichment_poll_interval_seconds: float
    pipeline_timeout_seconds: float
    basic_auth_user: str | None
    basic_auth_password: str | None
    gemini_api_key: str | None
    gemini_api_base_url: str
    gemini_summary_model: str
    gemini_translation_model: str
    gemini_timeout_seconds: float
    gemini_retry_after_max_seconds: float
    gemini_summary_soft_char_limit: int
    gemini_summary_hard_char_limit: int
    gemini_translation_char_limit: int
    localized_content_char_limit: int
    localized_xai_highlight_limit: int
    alerts_enabled: bool
    sentiment_only_alerts: bool
    sentiment_alert_min_confidence: float
    sentiment_positive_score_threshold: float
    sentiment_negative_score_threshold: float
    sentiment_max_input_chars: int
    xai_max_input_chars: int
    fail_on_suspicious_gpu_runtime: bool

    @property
    def basic_auth_enabled(self) -> bool:
        return bool(self.basic_auth_user and self.basic_auth_password)


def get_settings() -> AppSettings:
    """Load application settings from environment variables."""
    running_on_render = _env_flag("RENDER", default=False)
    running_on_zeabur = bool(
        os.getenv("ZEABUR_SERVICE_ID") or os.getenv("ZEABUR_PROJECT_ID")
    )
    return AppSettings(
        database_backend=(
            os.getenv("GENAI_DATABASE_BACKEND")
            or os.getenv("DATABASE_BACKEND")
            or "sqlite"
        ).lower(),
        postgres_dsn=os.getenv("GENAI_POSTGRES_DSN") or os.getenv("DATABASE_URL"),
        sqlite_path=os.getenv("GENAI_SQLITE_DB_PATH"),
        app_host=os.getenv("GENAI_APP_HOST", "127.0.0.1"),
        app_port=int(os.getenv("GENAI_APP_PORT", "8000")),
        worker_poll_interval_seconds=float(os.getenv("GENAI_WORKER_POLL_INTERVAL", "5")),
        worker_idle_log_interval_seconds=float(
            os.getenv("GENAI_WORKER_IDLE_LOG_INTERVAL", "60")
        ),
        enable_job_process_api=_env_flag(
            "GENAI_ENABLE_JOB_PROCESS_API",
            default=not running_on_render,
        ),
        use_worker_backed_direct_enrichment=_env_flag(
            "GENAI_USE_WORKER_FOR_DIRECT_ENRICHMENT",
            default=(running_on_render or running_on_zeabur),
        ),
        enable_inline_xai=_env_flag(
            "GENAI_ENABLE_INLINE_XAI",
            default=True,
        ),
        xai_backend=(os.getenv("GENAI_XAI_BACKEND") or "attention").strip().lower(),
        direct_enrichment_wait_timeout_seconds=float(
            os.getenv("GENAI_DIRECT_ENRICHMENT_WAIT_TIMEOUT", "30")
        ),
        direct_enrichment_poll_interval_seconds=float(
            os.getenv("GENAI_DIRECT_ENRICHMENT_POLL_INTERVAL", "0.5")
        ),
        pipeline_timeout_seconds=float(os.getenv("GENAI_PIPELINE_TIMEOUT_SECONDS", "90")),
        basic_auth_user=os.getenv("BASIC_AUTH_USER"),
        basic_auth_password=os.getenv("BASIC_AUTH_PASSWORD"),
        gemini_api_key=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"),
        gemini_api_base_url=(
            os.getenv("GEMINI_API_BASE_URL") or "https://generativelanguage.googleapis.com/v1beta"
        ).rstrip("/"),
        gemini_summary_model="gemini-2.5-flash-lite",
        gemini_translation_model="gemini-2.5-flash-lite",
        gemini_timeout_seconds=float(os.getenv("GEMINI_TIMEOUT_SECONDS", "20")),
        gemini_retry_after_max_seconds=float(os.getenv("GEMINI_RETRY_AFTER_MAX_SECONDS", "15")),
        gemini_summary_soft_char_limit=int(os.getenv("GEMINI_SUMMARY_SOFT_CHAR_LIMIT", "3500")),
        gemini_summary_hard_char_limit=int(os.getenv("GEMINI_SUMMARY_HARD_CHAR_LIMIT", "6500")),
        gemini_translation_char_limit=int(os.getenv("GEMINI_TRANSLATION_CHAR_LIMIT", "1200")),
        localized_content_char_limit=int(os.getenv("GENAI_LOCALIZED_CONTENT_CHAR_LIMIT", "700")),
        localized_xai_highlight_limit=int(os.getenv("GENAI_LOCALIZED_XAI_HIGHLIGHT_LIMIT", "2")),
        alerts_enabled=_env_flag("GENAI_ALERTS_ENABLED", default=True),
        sentiment_only_alerts=_env_flag("GENAI_SENTIMENT_ONLY_ALERTS", default=False),
        sentiment_alert_min_confidence=float(
            os.getenv("GENAI_SENTIMENT_ALERT_MIN_CONFIDENCE", "0.45")
        ),
        sentiment_positive_score_threshold=float(
            os.getenv("GENAI_SENTIMENT_POSITIVE_SCORE_THRESHOLD", "8")
        ),
        sentiment_negative_score_threshold=float(
            os.getenv("GENAI_SENTIMENT_NEGATIVE_SCORE_THRESHOLD", "-8")
        ),
        sentiment_max_input_chars=int(os.getenv("GENAI_SENTIMENT_MAX_INPUT_CHARS", "50000")),
        xai_max_input_chars=int(os.getenv("GENAI_XAI_MAX_INPUT_CHARS", "50000")),
        fail_on_suspicious_gpu_runtime=_env_flag(
            "GENAI_FAIL_ON_SUSPICIOUS_GPU_RUNTIME",
            default=False,
        ),
    )