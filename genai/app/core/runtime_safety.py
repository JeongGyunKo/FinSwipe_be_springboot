from __future__ import annotations

from functools import lru_cache
import importlib
from importlib import metadata


@lru_cache(maxsize=1)
def get_runtime_safety_snapshot() -> dict[str, object]:
    torch_installed = False
    torch_cuda_version: str | None = None
    torch_cuda_available = False
    torch_import_error: str | None = None

    try:
        torch = importlib.import_module("torch")  # type: ignore
        torch_installed = True
        torch_cuda_version = getattr(getattr(torch, "version", None), "cuda", None)
        torch_cuda_available = bool(getattr(torch, "cuda", None) and torch.cuda.is_available())
    except ModuleNotFoundError:
        torch_installed = False
    except Exception as exc:  # pragma: no cover - defensive runtime diagnostics
        torch_import_error = str(exc)

    installed_packages = {dist.metadata["Name"].lower() for dist in metadata.distributions()}
    gpu_packages = sorted(
        name for name in installed_packages if name.startswith("nvidia-") or name == "triton"
    )

    suspicious_gpu_runtime = bool(gpu_packages) or bool(torch_cuda_version)
    return {
        "torch_installed": torch_installed,
        "torch_cuda_version": torch_cuda_version,
        "torch_cuda_available": torch_cuda_available,
        "torch_import_error": torch_import_error,
        "gpu_packages_detected": gpu_packages,
        "suspicious_gpu_runtime": suspicious_gpu_runtime,
    }