from __future__ import annotations

import argparse
import time

from app.core import get_settings
from app.db import get_database_backend, ping_database_backend
from app.core.logging import configure_logging, get_logger, log_event
from app.core.runtime_safety import get_runtime_safety_snapshot
from app.services.job_processing_service import JobProcessingService


logger = get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Financial news enrichment worker")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process at most one queued job and exit.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=settings.worker_poll_interval_seconds,
        help="Seconds to sleep between queue polls in loop mode.",
    )
    parser.add_argument(
        "--idle-log-interval",
        type=float,
        default=settings.worker_idle_log_interval_seconds,
        help="Seconds between idle logs when no queued job is available.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    configure_logging()
    _run_startup_checks()
    service = JobProcessingService()
    log_event(
        logger,
        20,
        "worker_started",
        poll_interval_seconds=args.poll_interval,
        idle_log_interval_seconds=args.idle_log_interval,
    )

    if args.once:
        try:
            result = service.process_next_job()
        except Exception as exc:
            logger.exception("Worker one-shot execution failed.")
            log_event(
                logger,
                40,
                "worker_run_once_failed",
                error=str(exc),
            )
            raise SystemExit(1) from exc

        log_event(
            logger,
            20,
            "worker_run_once",
            processed=result.processed,
            retry_scheduled=result.retry_scheduled,
            news_id=result.news_id,
            message=result.message,
            analysis_status=result.analysis_status.value if result.analysis_status else None,
        )
        return

    last_idle_log_at = 0.0
    while True:
        try:
            result = service.process_next_job()
        except Exception as exc:
            logger.exception("Worker loop iteration failed.")
            log_event(
                logger,
                40,
                "worker_iteration_failed",
                error=str(exc),
            )
            time.sleep(args.poll_interval)
            continue

        if result.processed:
            event_name = "worker_retry_scheduled" if result.retry_scheduled else "worker_processed_job"
            log_event(
                logger,
                20,
                event_name,
                news_id=result.news_id,
                job_id=result.job.job_id if result.job else None,
                retry_scheduled=result.retry_scheduled,
                job_status=result.job.status.value if result.job else None,
                analysis_status=result.analysis_status.value if result.analysis_status else None,
                analysis_outcome=(
                    result.analysis_outcome.value if result.analysis_outcome else None
                ),
                error_code=result.error_code,
                message=result.message,
            )
        else:
            now = time.monotonic()
            if now - last_idle_log_at >= args.idle_log_interval:
                log_event(
                    logger,
                    20,
                    "worker_idle_no_job",
                    poll_interval_seconds=args.poll_interval,
                    message=result.message,
                )
                last_idle_log_at = now
        time.sleep(args.poll_interval)


def _run_startup_checks() -> None:
    settings = get_settings()
    backend = get_database_backend()
    errors: list[str] = []
    warnings: list[str] = []

    if backend in {"postgres", "postgresql"} and not settings.postgres_dsn:
        errors.append("Postgres backend selected but GENAI_POSTGRES_DSN/DATABASE_URL is missing.")

    db_ok, db_error = ping_database_backend()
    if not db_ok:
        errors.append(f"Database connectivity check failed: {db_error}")

    runtime = get_runtime_safety_snapshot()
    if runtime["suspicious_gpu_runtime"]:
        message = "GPU runtime artifacts detected in CPU-target service. Check Dockerfile/build path."
        if settings.fail_on_suspicious_gpu_runtime:
            errors.append(message)
        else:
            warnings.append(message)

    if not settings.gemini_api_key:
        warnings.append(
            "GEMINI_API_KEY is missing. Summarization/translation will remain empty."
        )

    if warnings:
        log_event(
            logger,
            30,
            "worker_startup_warning",
            backend=backend,
            warnings=" | ".join(warnings),
        )

    if errors:
        log_event(
            logger,
            40,
            "worker_startup_failed",
            backend=backend,
            errors=" | ".join(errors),
        )
        raise SystemExit(1)

    log_event(
        logger,
        20,
        "worker_startup_check_passed",
        backend=backend,
        fail_on_suspicious_gpu_runtime=settings.fail_on_suspicious_gpu_runtime,
        runtime_suspicious_gpu_runtime=bool(runtime["suspicious_gpu_runtime"]),
        runtime_torch_cuda_version=runtime["torch_cuda_version"],
        runtime_torch_cuda_available=bool(runtime["torch_cuda_available"]),
    )


if __name__ == "__main__":
    main()