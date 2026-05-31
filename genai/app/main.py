import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.routes.enrichment import router as enrichment_router
from app.api.routes.health import router as health_router
from app.api.routes.ingestion import router as ingestion_router
from app.api.routes.quiz import router as quiz_router
from app.api.routes.web import router as web_router
from app.core import get_settings
from app.core.auth import (
    basic_auth_required,
    is_basic_auth_authorized,
    unauthorized_basic_auth_response,
)
from app.core.logging import configure_logging, log_event
from app.core.runtime_safety import get_runtime_safety_snapshot
from app.db import initialize_database_backend


configure_logging()
settings = get_settings()
logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parent / "web"


app = FastAPI(
    title="Financial News Gen AI Service",
    version="0.1.0",
    description="Enrichment API for financial news articles.",
)


@app.on_event("startup")
async def warm_database_backend() -> None:
    runtime = get_runtime_safety_snapshot()
    if runtime["suspicious_gpu_runtime"]:
        log_event(
            logger,
            logging.ERROR if settings.fail_on_suspicious_gpu_runtime else logging.WARNING,
            "runtime_gpu_safety_check_failed",
            fail_on_suspicious_gpu_runtime=settings.fail_on_suspicious_gpu_runtime,
            runtime_torch_cuda_version=runtime["torch_cuda_version"],
            runtime_torch_cuda_available=bool(runtime["torch_cuda_available"]),
            runtime_gpu_packages_detected=",".join(runtime["gpu_packages_detected"]),
        )
        if settings.fail_on_suspicious_gpu_runtime:
            raise RuntimeError("Suspicious GPU runtime artifacts detected in CPU-target service.")

    async def _initialize_in_background() -> None:
        try:
            await asyncio.to_thread(initialize_database_backend)
        except Exception:
            logger.exception("Background database initialization failed during startup.")

    asyncio.create_task(_initialize_in_background())


@app.middleware("http")
async def basic_auth_middleware(request, call_next):
    if basic_auth_required(request) and not is_basic_auth_authorized(request):
        return unauthorized_basic_auth_response()
    return await call_next(request)

app.include_router(health_router)
app.include_router(web_router)
app.include_router(ingestion_router, prefix="/api/v1")
app.include_router(enrichment_router, prefix="/api/v1")
app.include_router(quiz_router, prefix="/api/v1")
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")