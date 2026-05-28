# Smoke Test Checklist

This checklist is for validating the enrichment pipeline against real external news links before backend integration.

## Goal

Confirm that the service can:
- accept a real article link
- fetch article text
- run the pipeline
- return a usable enrichment result
- expose clear failure states when it cannot complete

## Before You Start

1. Make sure the API is running.
2. Make sure the worker is running, or plan to trigger `POST /api/v1/jobs/process-next` manually.
3. Confirm DB connectivity:

```bash
python3 -m app.db.check
```

4. Confirm service health:

```bash
curl http://127.0.0.1:8000/health
```

Expected:
- `database_ok: true`
- `status: ok` or a clearly explained degraded status

## Recommended Link Types

Use at least 4 to 5 links across these categories:

1. Public financial article expected to succeed
2. Public mainstream news article expected to succeed
3. Long article for chunking/XAI behavior
4. Link likely to fail due to paywall or publisher restrictions
5. Link likely to fail due to anti-bot or unsupported rendering

## Run The Smoke Test

```bash
python3 scripts/smoke_test_enrichment.py \
  --title "Sample financial article title" \
  --link "https://example.com/article" \
  --ticker AAPL \
  --source Reuters \
  --poll-seconds 1
```

## What To Check

### 1. Intake

Expected:
- `intake.status_code == 200`
- `intake.body.queued == true` or existing active job message
- `intake.body.job.status` is `queued`, `processing`, or `retry_pending`

### 2. Worker Processing

Expected on success:
- `worker.status_code == 200`
- `worker.body.processed == true`
- `worker.body.analysis_status == "completed"` or `"completed_with_partial_results"`

Expected on retry:
- `worker.body.retry_scheduled == true`
- `worker.body.job.status == "retry_pending"`

Expected on failure:
- `worker.body.analysis_status` contains a meaningful stage failure

### 3. Final Status

Expected success path:
- `status.status_code == 200`
- `status.body.enrichment.analysis_outcome == "success"` or `"partial_success"`
- `status.body.enrichment.summary_3lines` has exactly 3 items
- `status.body.enrichment.sentiment` exists

Expected partial success path:
- summary exists
- sentiment may exist
- `analysis_status` may be `xai_failed`, `mixed_detection_failed`, or `completed_with_partial_results`
- `errors` contains useful stage messages

Expected fatal failure path:
- `analysis_outcome == "fatal_failure"`
- `analysis_status` explains the stage, such as `fetch_failed`
- `errors` is not empty

## Pass Criteria

Treat a smoke test as pass if all of these are true:
- the API accepts the request
- the job is traceable by `news_id`
- the final payload has a clear `analysis_status`
- successful articles return 3 summary lines
- failed articles return explicit errors, not silent empties

## Failure Diagnosis Guide

If `analysis_status == "fetch_failed"`:
- inspect `fetch_result.error_message`
- inspect `fetch_result.failure_category`
- inspect `fetch_result.publisher_domain`
- inspect `fetch_result.http_status_code`
- inspect `fetch_result.extraction_source`
  - `json_ld`: structured article body from schema/json-ld
  - `generic_json`: app-state JSON like `__NEXT_DATA__` or `application/json`
  - `paragraph_blocks`: visible `<p>` blocks
  - `container_block`: article/main/div container fallback
  - `meta_description`: only preview/meta text was available
  - `best_candidate`: generic highest-scoring HTML block fallback

If `analysis_status == "validate_failed"`:
- article text was fetched but extracted text was too short or unusable

If `analysis_status == "sentiment_failed"`:
- model/runtime dependency issue or chunk inference failure

If `analysis_status == "xai_failed"`:
- explanation stage failed but summary/sentiment may still be valid

If `analysis_status == "mixed_detection_failed"`:
- article enrichment may still be usable, but mixed/conflict metadata is incomplete

## Suggested Test Log Template

Record one line per article:

```text
news_id | domain | expected_result | actual_analysis_status | analysis_outcome | retry_scheduled | notes
```

Example:

```text
smoke-001 | reuters.com | success | completed | success | false | summary and sentiment returned
smoke-002 | marketwatch.com | partial | xai_failed | partial_success | false | usable summary, xai unavailable
smoke-003 | paywalled-site.com | fail | fetch_failed | fatal_failure | false | access blocked
```

## Domain Matrix Workflow

1. Save each smoke test result to a file:

```bash
python3 scripts/smoke_test_enrichment.py \
  --title "Sample title" \
  --link "https://example.com/article" \
  --ticker AAPL \
  --source Reuters > results/example-1.json
```

2. Aggregate the saved files:

```bash
python3 scripts/build_domain_matrix.py results/*.json --format table
```

3. Review the table for:
- domains with repeated `fatal_failure`
- domains falling back to `meta_description`
- domains succeeding mainly through `generic_json` or `paragraph_blocks`
- recurring failure categories like `ssl_error`, `access_blocked`, or `rate_limited`
- the recommended support tier:
  - `primary`: stable enough for first-tier support
  - `secondary`: usable but still needs more validation
  - `blocked`: currently poor candidate for direct link fetch support
  - `investigate`: not enough evidence yet or diagnostics still ambiguous

## Batch Smoke Suite

If you want to test multiple links in one run, create a JSON config and run:

```bash
python3 scripts/run_smoke_suite.py \
  --config smoke_suite.json \
  --output-dir results
```

This will:
- run the smoke test for each configured article
- save one JSON result file per run
- save `suite_summary.json` and `suite_summary.md`
- print the aggregated domain matrix after the suite finishes

## Minimum Exit Criteria Before BE Integration

Move to backend integration only when:
- at least 3 public links complete successfully
- at least 1 failure case returns explicit fetch diagnostics
- retryable failures correctly become `retry_pending`
- the final `GET /api/v1/news/{news_id}` response is stable and understandable