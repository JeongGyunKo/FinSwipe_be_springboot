from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.build_domain_matrix import (
    build_domain_matrix,
    render_domain_matrix_markdown,
    render_domain_matrix_table,
)
from scripts.smoke_test_enrichment import run_smoke_test


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a suite of smoke tests from a JSON config and save per-article results."
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Path to a JSON file containing smoke test cases.",
    )
    parser.add_argument(
        "--output-dir",
        default="results",
        help="Directory where per-article smoke test JSON outputs will be written.",
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="Base URL for the running Gen AI service.",
    )
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=0.0,
        help="Optional delay before the final status request for each test.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="HTTP request timeout in seconds.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    config_path = Path(args.config)
    output_dir = Path(args.output_dir)
    cases = load_suite_config(config_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    saved_paths: list[Path] = []
    for index, case in enumerate(cases, start=1):
        news_id = case.get("news_id") or f"suite-{index:02d}-{uuid4().hex[:8]}"
        result = run_smoke_test(
            base_url=args.base_url,
            news_id=news_id,
            title=str(case["title"]),
            link=str(case["link"]),
            tickers=list(case.get("ticker") or []),
            source=case.get("source"),
            published_at=case.get("published_at"),
            skip_worker=bool(case.get("skip_worker", False)),
            poll_seconds=args.poll_seconds,
            timeout=args.timeout,
        )
        output_path = output_dir / f"{news_id}.json"
        output_path.write_text(json.dumps(result, ensure_ascii=True, indent=2), encoding="utf-8")
        saved_paths.append(output_path)

    summaries = [json.loads(path.read_text(encoding="utf-8")) for path in saved_paths]
    matrix = build_domain_matrix_from_payloads(saved_paths, summaries)
    summary_json = build_suite_summary(saved_paths, matrix)
    summary_json_path = output_dir / "suite_summary.json"
    summary_markdown_path = output_dir / "suite_summary.md"
    summary_json_path.write_text(
        json.dumps(summary_json, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    summary_markdown_path.write_text(
        render_domain_matrix_markdown(matrix),
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "saved_results": [str(path) for path in saved_paths],
                "summary_json": str(summary_json_path),
                "summary_markdown": str(summary_markdown_path),
            },
            ensure_ascii=True,
            indent=2,
        )
    )
    print()
    print(render_domain_matrix_table(matrix))
    return 0


def load_suite_config(path: Path) -> list[dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Smoke suite config must be a JSON array of test case objects.")
    validated_cases: list[dict[str, object]] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("Each smoke suite item must be an object.")
        if "title" not in item or "link" not in item:
            raise ValueError("Each smoke suite item must include title and link.")
        validated_cases.append(item)
    return validated_cases


def build_domain_matrix_from_payloads(
    paths: list[Path],
    payloads: list[dict[str, object]],
) -> list[dict[str, object]]:
    summaries = []
    for path, payload in zip(paths, payloads, strict=True):
        status_body = ((payload.get("status") or {}).get("body") or {})
        raw_news = status_body.get("raw_news") or {}
        enrichment = status_body.get("enrichment") or {}
        fetch_result = enrichment.get("fetch_result") or {}
        diagnostics = payload.get("diagnostics") or {}

        link = str(raw_news.get("link") or fetch_result.get("link") or "")
        domain = str(fetch_result.get("publisher_domain") or "unknown")
        if not domain and "://" in link:
            domain = link.split("/")[2]

        summaries.append(
            {
                "file": str(path),
                "domain": domain or "unknown",
                "analysis_status": str(
                    diagnostics.get("analysis_status")
                    or enrichment.get("analysis_status")
                    or "unknown"
                ),
                "analysis_outcome": str(
                    diagnostics.get("analysis_outcome")
                    or enrichment.get("analysis_outcome")
                    or "unknown"
                ),
                "extraction_source": str(
                    diagnostics.get("extraction_source")
                    or fetch_result.get("extraction_source")
                    or "unknown"
                ),
                "failure_category": str(
                    diagnostics.get("failure_category")
                    or fetch_result.get("failure_category")
                    or "none"
                ),
            }
        )

    return build_domain_matrix(summaries)


def build_suite_summary(
    saved_paths: list[Path],
    matrix: list[dict[str, object]],
) -> dict[str, object]:
    total_runs = sum(int(row["total_runs"]) for row in matrix)
    total_success = sum(int(row["success_count"]) for row in matrix)
    total_partial = sum(int(row["partial_success_count"]) for row in matrix)
    total_fatal = sum(int(row["fatal_failure_count"]) for row in matrix)

    return {
        "saved_results": [str(path) for path in saved_paths],
        "total_runs": total_runs,
        "total_success": total_success,
        "total_partial_success": total_partial,
        "total_fatal_failure": total_fatal,
        "domains": matrix,
    }


if __name__ == "__main__":
    raise SystemExit(main())