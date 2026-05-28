from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from dataclasses import asdict, dataclass
from typing import Callable

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

from app.services.xai.attention_explainer import explain_sentiment as explain_attention


SAMPLES = [
    {
        "name": "positive",
        "title": "Company raises outlook after quarterly results",
        "article_text": (
            "Revenue rose 12% year over year. "
            "Operating margin improved in the quarter. "
            "Management raised full-year guidance."
        ),
    },
    {
        "name": "negative",
        "title": "Company warns on demand weakness",
        "article_text": (
            "Revenue fell sharply in the quarter. "
            "Margins compressed as costs rose. "
            "Management cut guidance for the full year."
        ),
    },
    {
        "name": "mixed",
        "title": "Mixed signals after earnings",
        "article_text": (
            "Revenue rose ahead of expectations. "
            "Margins deteriorated because of restructuring charges. "
            "Management maintained annual guidance."
        ),
    },
]


@dataclass(frozen=True, slots=True)
class SampleBenchmark:
    backend: str
    sample: str
    iteration_durations_ms: list[float]
    mean_duration_ms: float
    median_duration_ms: float
    highlight_count: int
    target_label: str
    truncated: bool


@dataclass(frozen=True, slots=True)
class BackendBenchmark:
    backend: str
    sample_results: list[SampleBenchmark]
    overall_mean_duration_ms: float
    overall_median_duration_ms: float


def _benchmark_backend(
    *,
    backend_name: str,
    explain_fn: Callable[[str, str], object],
    iterations: int,
    warmup: bool,
) -> BackendBenchmark:
    sample_results: list[SampleBenchmark] = []

    for sample in SAMPLES:
        title = sample["title"]
        article_text = sample["article_text"]

        if warmup:
            explain_fn(title, article_text)

        durations_ms: list[float] = []
        last_result = None
        for _ in range(iterations):
            started_at = time.perf_counter()
            last_result = explain_fn(title, article_text)
            durations_ms.append(round((time.perf_counter() - started_at) * 1000, 3))

        assert last_result is not None
        sample_results.append(
            SampleBenchmark(
                backend=backend_name,
                sample=sample["name"],
                iteration_durations_ms=durations_ms,
                mean_duration_ms=round(statistics.mean(durations_ms), 3),
                median_duration_ms=round(statistics.median(durations_ms), 3),
                highlight_count=len(last_result.highlights),
                target_label=last_result.target_label.value,
                truncated=bool(last_result.truncated),
            )
        )

    all_durations = [
        duration
        for sample_result in sample_results
        for duration in sample_result.iteration_durations_ms
    ]
    return BackendBenchmark(
        backend=backend_name,
        sample_results=sample_results,
        overall_mean_duration_ms=round(statistics.mean(all_durations), 3),
        overall_median_duration_ms=round(statistics.median(all_durations), 3),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark XAI backends on shared samples.")
    parser.add_argument("--iterations", type=int, default=1, help="Iterations per sample.")
    parser.add_argument(
        "--skip-warmup",
        action="store_true",
        help="Skip one warmup call before timed iterations.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of a text report.",
    )
    args = parser.parse_args()

    backends = [
        ("attention", explain_attention),
    ]
    results = [
        _benchmark_backend(
            backend_name=name,
            explain_fn=fn,
            iterations=max(1, args.iterations),
            warmup=not args.skip_warmup,
        )
        for name, fn in backends
    ]

    if args.json:
        print(json.dumps([asdict(item) for item in results], indent=2))
        return

    for backend_result in results:
        print(f"[{backend_result.backend}]")
        print(
            f"overall mean={backend_result.overall_mean_duration_ms} ms "
            f"median={backend_result.overall_median_duration_ms} ms"
        )
        for sample_result in backend_result.sample_results:
            print(
                f"  - {sample_result.sample}: "
                f"mean={sample_result.mean_duration_ms} ms "
                f"median={sample_result.median_duration_ms} ms "
                f"label={sample_result.target_label} "
                f"highlights={sample_result.highlight_count} "
                f"truncated={sample_result.truncated}"
            )


if __name__ == "__main__":
    main()