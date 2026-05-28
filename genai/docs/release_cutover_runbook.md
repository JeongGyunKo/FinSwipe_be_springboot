# GenAI Release Cutover Runbook

## 1) Required Runtime Settings (Zeabur)

Set these for both web and worker unless noted:

- `GEMINI_API_KEY=<...>`
- `GEMINI_API_BASE_URL=https://generativelanguage.googleapis.com/v1beta`
- `GENAI_PIPELINE_TIMEOUT_SECONDS=90`
- `GEMINI_RETRY_AFTER_MAX_SECONDS=15`
- `GENAI_SENTIMENT_MAX_INPUT_CHARS=12000`
- `GENAI_XAI_MAX_INPUT_CHARS=9000`
- `GENAI_USE_WORKER_FOR_DIRECT_ENRICHMENT=true`
- `GENAI_ENABLE_INLINE_XAI=true`

Web command:

- `uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}`

Worker command:

- `python -m app.workers.enrichment_worker --poll-interval 5`

## 2) Stage 100-Article Validation

1. Prepare a JSON array config with 100 articles and run:
   - `python3 scripts/run_smoke_suite.py --config <path/to/suite_100.json> --output-dir results/stage100 --base-url <staging-url>`
2. Inspect generated:
   - `results/stage100/suite_summary.json`
   - `results/stage100/suite_summary.md`
3. Run release gate:
   - `python3 scripts/release_gate.py --base-url <staging-url> --suite-summary results/stage100/suite_summary.json`
4. Gate passes only if command exits `0`.

## 3) Canary Rollout (10-20%)

1. Route 10% traffic to new deployment.
2. Monitor every 5-10 minutes:
   - `GET /api/v1/operations/stats`
   - `summarize_failed_ratio`
   - `timeout_failure_ratio`
   - `gemini_rate_limited_ratio`
   - `average_cleaned_to_raw_ratio`
3. If stable for at least 60 minutes, increase to 20%.
4. Re-run `release_gate.py` with fresh suite output.

## 4) Promotion to 100%

Promote only when all are true:

- `release_gate.py` pass
- `timeout_failure_ratio <= 0.05`
- `summarize_failed_ratio <= 0.15`
- `gemini_rate_limited_ratio <= 0.20`
- `average_cleaned_to_raw_ratio >= 0.30`
- No sustained increase in `fatal_failure` outcomes

## 5) Rollback Triggers

Rollback immediately if one of below persists for 10+ minutes:

- `timeout_failure_ratio > 0.10`
- `fatal_failure` spike > 2x baseline
- `summary_3lines_ko` empty rate > 25%
- `xai_display` missing rate > 25%