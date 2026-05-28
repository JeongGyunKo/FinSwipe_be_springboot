from __future__ import annotations

import json
from pathlib import Path

from scripts.build_domain_matrix import (
    build_domain_matrix,
    load_smoke_test_summary,
    render_domain_matrix_table,
)


def test_load_smoke_test_summary_extracts_domain_and_diagnostics(tmp_path: Path) -> None:
    sample = {
        "diagnostics": {
            "analysis_status": "completed",
            "analysis_outcome": "success",
            "extraction_source": "paragraph_blocks",
            "failure_category": None,
        },
        "status": {
            "body": {
                "raw_news": {
                    "link": "https://apnews.com/article/example",
                },
                "enrichment": {
                    "fetch_result": {
                        "publisher_domain": "apnews.com",
                    }
                },
            }
        },
    }
    path = tmp_path / "apnews.json"
    path.write_text(json.dumps(sample), encoding="utf-8")

    summary = load_smoke_test_summary(path)

    assert summary["domain"] == "apnews.com"
    assert summary["analysis_status"] == "completed"
    assert summary["analysis_outcome"] == "success"
    assert summary["extraction_source"] == "paragraph_blocks"
    assert summary["failure_category"] == "none"


def test_build_domain_matrix_groups_results_by_domain() -> None:
    matrix = build_domain_matrix(
        [
            {
                "file": "ap-1.json",
                "domain": "apnews.com",
                "analysis_status": "completed",
                "analysis_outcome": "success",
                "extraction_source": "paragraph_blocks",
                "failure_category": "none",
            },
            {
                "file": "ap-2.json",
                "domain": "apnews.com",
                "analysis_status": "validate_failed",
                "analysis_outcome": "fatal_failure",
                "extraction_source": "meta_description",
                "failure_category": "none",
            },
            {
                "file": "yahoo-1.json",
                "domain": "finance.yahoo.com",
                "analysis_status": "fetch_failed",
                "analysis_outcome": "fatal_failure",
                "extraction_source": "unknown",
                "failure_category": "ssl_error",
            },
        ]
    )

    assert matrix[0]["domain"] == "apnews.com"
    assert matrix[0]["total_runs"] == 2
    assert matrix[0]["success_count"] == 1
    assert matrix[0]["fatal_failure_count"] == 1
    assert matrix[0]["support_tier"] == "secondary"
    assert matrix[0]["extraction_source_counts"] == {
        "meta_description": 1,
        "paragraph_blocks": 1,
    }
    assert matrix[1]["domain"] == "finance.yahoo.com"
    assert matrix[1]["failure_category_counts"] == {"ssl_error": 1}
    assert matrix[1]["support_tier"] == "investigate"


def test_render_domain_matrix_table_is_human_readable() -> None:
    table = render_domain_matrix_table(
        [
            {
                "domain": "apnews.com",
                "support_tier": "secondary",
                "total_runs": 2,
                "success_count": 1,
                "partial_success_count": 0,
                "fatal_failure_count": 1,
                "extraction_source_counts": {"paragraph_blocks": 1, "meta_description": 1},
                "failure_category_counts": {},
                "files": ["ap-1.json", "ap-2.json"],
            }
        ]
    )

    assert "domain | tier | total | success | partial | fatal" in table
    assert (
        "apnews.com | secondary | 2 | 1 | 0 | 1 | meta_description:1, paragraph_blocks:1 | -"
        in table
    )