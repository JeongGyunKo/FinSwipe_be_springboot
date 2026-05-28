from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Aggregate smoke test JSON outputs into a domain-level success/failure matrix."
    )
    parser.add_argument(
        "paths",
        nargs="+",
        help="Smoke test JSON files to aggregate.",
    )
    parser.add_argument(
        "--format",
        choices=("json", "table"),
        default="table",
        help="Output format for the domain matrix.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    summaries = [load_smoke_test_summary(Path(path)) for path in args.paths]
    matrix = build_domain_matrix(summaries)

    if args.format == "json":
        print(json.dumps(matrix, ensure_ascii=True, indent=2))
    else:
        print(render_domain_matrix_table(matrix))
    return 0


def load_smoke_test_summary(path: Path) -> dict[str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    status_body = ((payload.get("status") or {}).get("body") or {})
    raw_news = status_body.get("raw_news") or {}
    enrichment = status_body.get("enrichment") or {}
    fetch_result = enrichment.get("fetch_result") or {}
    diagnostics = payload.get("diagnostics") or {}

    link = str(raw_news.get("link") or fetch_result.get("link") or "")
    domain = str(fetch_result.get("publisher_domain") or urlparse(link).netloc or "unknown")

    return {
        "file": str(path),
        "domain": domain,
        "analysis_status": str(
            diagnostics.get("analysis_status") or enrichment.get("analysis_status") or "unknown"
        ),
        "analysis_outcome": str(
            diagnostics.get("analysis_outcome") or enrichment.get("analysis_outcome") or "unknown"
        ),
        "extraction_source": str(
            diagnostics.get("extraction_source") or fetch_result.get("extraction_source") or "unknown"
        ),
        "failure_category": str(
            diagnostics.get("failure_category") or fetch_result.get("failure_category") or "none"
        ),
    }


def build_domain_matrix(summaries: list[dict[str, str]]) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for summary in summaries:
        grouped[summary["domain"]].append(summary)

    matrix: list[dict[str, object]] = []
    for domain, items in sorted(grouped.items()):
        outcome_counts = Counter(item["analysis_outcome"] for item in items)
        status_counts = Counter(item["analysis_status"] for item in items)
        extraction_counts = Counter(item["extraction_source"] for item in items)
        failure_counts = Counter(
            item["failure_category"] for item in items if item["failure_category"] != "none"
        )
        total_runs = len(items)
        success_count = outcome_counts.get("success", 0)
        partial_success_count = outcome_counts.get("partial_success", 0)
        fatal_failure_count = outcome_counts.get("fatal_failure", 0)
        support_tier, support_reason = classify_domain_support(
            total_runs=total_runs,
            success_count=success_count,
            partial_success_count=partial_success_count,
            fatal_failure_count=fatal_failure_count,
            extraction_counts=extraction_counts,
            failure_counts=failure_counts,
        )

        matrix.append(
            {
                "domain": domain,
                "total_runs": total_runs,
                "success_count": success_count,
                "partial_success_count": partial_success_count,
                "fatal_failure_count": fatal_failure_count,
                "support_tier": support_tier,
                "support_reason": support_reason,
                "analysis_status_counts": dict(sorted(status_counts.items())),
                "extraction_source_counts": dict(sorted(extraction_counts.items())),
                "failure_category_counts": dict(sorted(failure_counts.items())),
                "files": [item["file"] for item in items],
            }
        )

    return matrix


def render_domain_matrix_table(matrix: list[dict[str, object]]) -> str:
    lines = [
        "domain | tier | total | success | partial | fatal | extraction_sources | failure_categories",
        "--- | --- | ---: | ---: | ---: | ---: | --- | ---",
    ]
    for row in matrix:
        lines.append(
            " | ".join(
                [
                    str(row["domain"]),
                    str(row["support_tier"]),
                    str(row["total_runs"]),
                    str(row["success_count"]),
                    str(row["partial_success_count"]),
                    str(row["fatal_failure_count"]),
                    _format_counter_dict(row["extraction_source_counts"]),
                    _format_counter_dict(row["failure_category_counts"]),
                ]
            )
        )
    return "\n".join(lines)


def render_domain_matrix_markdown(matrix: list[dict[str, object]]) -> str:
    lines = [
        "# Domain Support Report",
        "",
        render_domain_matrix_table(matrix),
        "",
        "## Tier Notes",
    ]
    for row in matrix:
        lines.append(
            f"- `{row['domain']}`: `{row['support_tier']}`"
            f" - {row['support_reason']}"
        )
    return "\n".join(lines)


def _format_counter_dict(values: object) -> str:
    if not isinstance(values, dict) or not values:
        return "-"
    return ", ".join(f"{key}:{values[key]}" for key in sorted(values))


def classify_domain_support(
    *,
    total_runs: int,
    success_count: int,
    partial_success_count: int,
    fatal_failure_count: int,
    extraction_counts: Counter[str],
    failure_counts: Counter[str],
) -> tuple[str, str]:
    if total_runs == 0:
        return ("investigate", "No smoke test results are available yet.")

    success_rate = success_count / total_runs
    usable_rate = (success_count + partial_success_count) / total_runs

    if failure_counts.get("access_blocked", 0) >= max(1, total_runs // 2):
        return ("blocked", "Publisher often blocks direct fetching with access or anti-bot rules.")
    if failure_counts.get("ssl_error", 0) == total_runs:
        return ("investigate", "All observed runs failed on SSL/TLS setup before article analysis.")
    if success_rate >= 0.8 and total_runs >= 3:
        return ("primary", "Domain consistently completes successfully and is a good first-tier target.")
    if usable_rate >= 0.5 and success_count >= 1:
        if extraction_counts.get("meta_description", 0) >= success_count:
            return (
                "secondary",
                "Domain is usable, but it often relies on preview/meta extraction rather than full article body.",
            )
        return ("secondary", "Domain is usable, but still needs more runs before primary support.")
    if fatal_failure_count >= max(2, total_runs // 2):
        return ("blocked", "Domain currently fails often enough that it should not be treated as supported.")
    return ("investigate", "Domain needs more smoke test evidence before assigning a support tier.")


if __name__ == "__main__":
    raise SystemExit(main())