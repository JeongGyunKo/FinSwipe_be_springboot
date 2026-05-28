from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from uuid import uuid4

import requests


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run an end-to-end enrichment smoke test against the running API."
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8000",
        help="Base URL for the running Gen AI service.",
    )
    parser.add_argument(
        "--news-id",
        default=None,
        help="Optional news identifier. One is generated automatically if omitted.",
    )
    parser.add_argument(
        "--title",
        required=True,
        help="Article title to send to the intake endpoint.",
    )
    parser.add_argument(
        "--link",
        required=True,
        help="Original article URL to enrich.",
    )
    parser.add_argument(
        "--ticker",
        action="append",
        default=[],
        help="Ticker symbol. Repeat the flag to send multiple tickers.",
    )
    parser.add_argument(
        "--source",
        default=None,
        help="Optional article source.",
    )
    parser.add_argument(
        "--published-at",
        default=None,
        help="Optional ISO-8601 publication timestamp.",
    )
    parser.add_argument(
        "--skip-worker",
        action="store_true",
        help="Only queue the job and fetch current status without triggering worker processing.",
    )
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=0.0,
        help="Optional delay before the final status request.",
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
    news_id = args.news_id or f"smoke-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}"
    result = run_smoke_test(
        base_url=args.base_url,
        news_id=news_id,
        title=args.title,
        link=args.link,
        tickers=args.ticker or [],
        source=args.source,
        published_at=args.published_at,
        skip_worker=args.skip_worker,
        poll_seconds=args.poll_seconds,
        timeout=args.timeout,
    )
    print(json.dumps(result, ensure_ascii=True, indent=2))

    status_payload = ((result.get("status") or {}).get("body") or {})
    enrichment = status_payload.get("enrichment") or {}
    analysis_outcome = enrichment.get("analysis_outcome")
    if analysis_outcome in {"success", "partial_success"}:
        return 0
    return 1


def run_smoke_test(
    *,
    base_url: str,
    news_id: str,
    title: str,
    link: str,
    tickers: list[str],
    source: str | None,
    published_at: str | None,
    skip_worker: bool,
    poll_seconds: float,
    timeout: float,
) -> dict[str, object]:
    session = requests.Session()

    intake_payload = {
        "news_id": news_id,
        "title": title,
        "link": link,
        "ticker": tickers or None,
        "source": source,
        "published_at": published_at,
    }

    intake_response = _request_json(
        session,
        "post",
        f"{base_url.rstrip('/')}/api/v1/news/intake",
        json_body=intake_payload,
        timeout=timeout,
    )

    worker_response = None
    if not skip_worker:
        worker_response = _request_json(
            session,
            "post",
            f"{base_url.rstrip('/')}/api/v1/jobs/process-next",
            timeout=timeout,
        )

    if poll_seconds > 0:
        time.sleep(poll_seconds)

    status_response = _request_json(
        session,
        "get",
        f"{base_url.rstrip('/')}/api/v1/news/{news_id}",
        timeout=timeout,
    )

    return {
        "intake": intake_response,
        "worker": worker_response,
        "status": status_response,
        "diagnostics": _build_diagnostics(status_response),
    }


def _build_diagnostics(status_response: dict[str, object]) -> dict[str, object]:
    status_payload = status_response.get("body", {})
    enrichment = status_payload.get("enrichment") or {}
    fetch_result = enrichment.get("fetch_result") or {}
    summary_lines = enrichment.get("summary_3lines") or []
    sentiment = enrichment.get("sentiment") or {}

    return {
        "analysis_status": enrichment.get("analysis_status"),
        "analysis_outcome": enrichment.get("analysis_outcome"),
        "summary_line_count": len(summary_lines),
        "sentiment_label": sentiment.get("label"),
        "fetch_status": fetch_result.get("fetch_status"),
        "extraction_source": fetch_result.get("extraction_source"),
        "failure_category": fetch_result.get("failure_category"),
        "error_message": fetch_result.get("error_message"),
    }


def _request_json(
    session: requests.Session,
    method: str,
    url: str,
    *,
    timeout: float,
    json_body: dict | None = None,
) -> dict[str, object]:
    response = session.request(
        method=method.upper(),
        url=url,
        json=json_body,
        timeout=timeout,
    )
    try:
        body = response.json()
    except ValueError:
        body = response.text

    return {
        "status_code": response.status_code,
        "ok": response.ok,
        "body": body,
    }


if __name__ == "__main__":
    raise SystemExit(main())