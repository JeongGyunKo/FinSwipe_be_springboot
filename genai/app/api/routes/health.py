import logging

from fastapi import APIRouter
from fastapi.responses import Response

from app.core import get_settings
from app.core.runtime_safety import get_runtime_safety_snapshot
from app.db import get_database_backend, ping_database_backend

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health", summary="Health check")
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@router.head("/health", include_in_schema=False)
async def health_check_head() -> Response:
    return Response(status_code=200)


@router.get("/health/deep", summary="Deep health check")
async def deep_health_check() -> dict[str, str | bool | None]:
    database_ok, database_error = ping_database_backend()
    if database_error:
        logger.error("데이터베이스 연결 실패: %s", database_error)
    runtime = get_runtime_safety_snapshot()
    settings = get_settings()
    return {
        "status": "ok" if database_ok else "degraded",
        "database_backend": get_database_backend(),
        "database_ok": database_ok,
        "database_error": not database_ok,
        "guard_fail_on_suspicious_gpu_runtime": settings.fail_on_suspicious_gpu_runtime,
        "runtime_torch_installed": bool(runtime["torch_installed"]),
        "runtime_torch_cuda_version": runtime["torch_cuda_version"],
        "runtime_torch_cuda_available": bool(runtime["torch_cuda_available"]),
        "runtime_gpu_packages_detected": ",".join(runtime["gpu_packages_detected"]),
        "runtime_suspicious_gpu_runtime": bool(runtime["suspicious_gpu_runtime"]),
    }