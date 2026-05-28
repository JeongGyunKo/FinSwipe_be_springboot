from __future__ import annotations

import json
from pathlib import Path

from scripts.build_domain_matrix import render_domain_matrix_markdown
from scripts.run_smoke_suite import (
    build_domain_matrix_from_payloads,
    build_suite_summary,
    load_suite_config,
)


def test_load_suite_config_validates_required_fields(tmp_path: Path) -> None:
    config_path = tmp_path / "suite.json"
    config_path.write_text(
        json.dumps(
            [
                {
                    "title": "AP article",
                    "link": "https://apnews.com/article/example",
                    "ticker": ["SPY"],
                    "source": "AP News",
                }
            ]
        ),
        encoding="utf-8",
    )

    cases = load_suite_config(config_path)

    assert len(cases) == 1
    assert cases[0]["title"] == "AP article"


def test_build_domain_matrix_from_payloads_returns_support_tier(tmp_path: Path) -> None:
    path = tmp_path / "apnews.json"
    payload = {
        "diagnostics": {
            "analysis_status": "completed",
            "analysis_outcome": "success",
            "extraction_source": "paragraph_blocks",
            "failure_category": None,
        },
        "status": {
            "body": {
                "raw_news": {"link": "https://apnews.com/article/example"},
                "enrichment": {
                    "fetch_result": {
                        "publisher_domain": "apnews.com",
                        "extraction_source": "paragraph_blocks",
                        "failure_category": None,
                    }
                },
            }
        },
    }
    matrix = build_domain_matrix_from_payloads([path], [payload])

    assert matrix[0]["domain"] == "apnews.com"
    assert matrix[0]["support_tier"] in {"secondary", "investigate", "primary", "blocked"}


def test_build_suite_summary_and_markdown_render(tmp_path: Path) -> None:
    path = tmp_path / "apnews.json"
    matrix = [
        {
            "domain": "apnews.com",
            "total_runs": 2,
            "success_count": 1,
            "partial_success_count": 1,
            "fatal_failure_count": 0,
            "support_tier": "secondary",
            "support_reason": "Domain is usable, but still needs more runs before primary support.",
            "analysis_status_counts": {"completed": 2},
            "extraction_source_counts": {"paragraph_blocks": 2},
            "failure_category_counts": {},
            "files": [str(path)],
        }
    ]

    summary = build_suite_summary([path], matrix)
    markdown = render_domain_matrix_markdown(matrix)

    assert summary["total_runs"] == 2
    assert summary["total_success"] == 1
    assert summary["total_partial_success"] == 1
    assert summary["total_fatal_failure"] == 0
    assert summary["domains"][0]["domain"] == "apnews.com"
    assert "# Domain Support Report" in markdown
    assert "`apnews.com`: `secondary`" in markdown