# Financial News Gen AI Service

금융 뉴스 기사에 대해 요약, 감성 분석, XAI 하이라이트, 혼합 신호 감지를 수행하는 FastAPI 기반 분석 서비스입니다. 백엔드에서 기사 메타데이터 또는 직접 제공된 텍스트를 전달하면, 서비스가 이를 저장하고 분석 결과를 반환합니다.

## 핵심 기능

- 기사 URL 기반 수집 및 분석
- `article_text` / `summary_text` 직접 입력 기반 분석
- 비동기 job 큐 처리
- 3줄 요약 생성
- 감성 분석 및 XAI 하이라이트 생성
- 혼합/충돌 신호 탐지

## 권장 실행 구조

운영 환경에서는 웹 서버와 worker를 분리하는 것을 권장합니다.

- 웹 서버: 요청 수신, job 생성, 결과 조회
- worker: 기사 fetch, 정제, 요약, 감성 분석, XAI, 저장

로컬 개발은 한 프로젝트 안에서 두 프로세스로 실행하면 됩니다.

## 로컬 Postgres 실행

1. `.env.example`을 `.env`로 복사합니다.
2. 필요한 값을 로컬 환경에 맞게 수정합니다.
3. Postgres를 실행합니다.

```bash
docker compose up -d postgres
```

4. 의존성을 설치합니다.

```bash
pip install -e .
```

5. API 서버를 실행합니다.

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

6. 다른 터미널에서 worker를 실행합니다.

```bash
python3 -m app.workers.enrichment_worker --poll-interval 5
```

## DB 설정 점검

전체 API를 띄우지 않고 현재 DB 설정만 빠르게 확인할 수 있습니다.

```bash
python3 -m app.db.check
```

예시 출력:

```json
{
  "database_backend": "postgres",
  "database_ok": false,
  "database_error": "connection refused",
  "postgres_dsn_configured": true,
  "sqlite_path": null
}
```

## 주요 API 흐름

### 1. 비동기 큐 기반 처리

백엔드에서 기사 메타데이터를 저장하고, worker가 뒤에서 분석을 처리하는 흐름입니다.

- `POST /api/v1/news/intake`
- `POST /api/v1/news/intake-text`
- `GET /api/v1/news/{news_id}`
- `GET /api/v1/news/{news_id}/result`

### 2. 직접 분석 요청

직접 분석 API는 요청을 받아 내부적으로 분석 결과를 기다려 응답합니다.

- `POST /api/v1/articles/enrich`
- `POST /api/v1/articles/enrich-text`

환경에 따라 `GENAI_USE_WORKER_FOR_DIRECT_ENRICHMENT=true` 이면 worker가 job을 처리해야 결과가 반환됩니다.

## 직접 텍스트 분석 예시

라이선스된 본문 또는 요약문을 직접 받을 수 있다면 URL 크롤링 없이 바로 분석할 수 있습니다.

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/articles/enrich-text" \
  -H "Content-Type: application/json" \
  -d '{
    "news_id": "provider-123",
    "title": "Apple shares rise after earnings",
    "link": "https://provider.example.com/article/123",
    "ticker": ["AAPL"],
    "source": "Licensed Provider",
    "article_text": "Full licensed article text goes here."
  }'
```

`summary_text`만 있는 경우에도 요청할 수 있습니다. 기존 레거시 호환을 위해 `text` 필드도 `summary_text`로 해석합니다.

비동기 큐 흐름을 쓰려면 아래처럼 저장 후 worker가 처리하게 할 수 있습니다.

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/news/intake-text" \
  -H "Content-Type: application/json" \
  -d '{
    "news_id": "provider-124",
    "title": "Apple shares rise after earnings",
    "link": "https://provider.example.com/article/124",
    "ticker": ["AAPL"],
    "source": "Licensed Provider",
    "summary_text": "Apple shares rose after better-than-expected earnings."
  }'
```

## 스모크 테스트

실행 중인 API에 대해 BE 관점의 빠른 점검을 할 수 있습니다.

```bash
python3 scripts/smoke_test_enrichment.py \
  --title "Apple shares rise after earnings" \
  --link "https://example.com/article" \
  --ticker AAPL \
  --source Reuters
```

수행 내용:

- `POST /api/v1/news/intake`
- 필요 시 `POST /api/v1/jobs/process-next`
- `GET /api/v1/news/{news_id}`
- 전체 JSON 결과 출력

자주 쓰는 옵션:

- `--base-url http://127.0.0.1:8000`
- `--skip-worker`
- `--poll-seconds 2`
- `--news-id custom-id-123`

상세 점검 문서:

- `docs/smoke_test_checklist.md`

## 도메인 매트릭스

스모크 테스트 결과를 저장한 뒤 도메인별 품질 매트릭스를 만들 수 있습니다.

```bash
python3 scripts/smoke_test_enrichment.py \
  --title "Sample title" \
  --link "https://example.com/article" \
  --ticker AAPL \
  --source Reuters > results/apnews-1.json
```

```bash
python3 scripts/build_domain_matrix.py results/*.json --format table
```

확인 가능한 항목:

- 도메인별 성공/실패 비율
- 실제 사용된 추출 경로
- 반복되는 실패 유형
- 지원 권장 등급: `primary`, `secondary`, `blocked`, `investigate`

## 스모크 스위트

여러 링크를 한 번에 점검하고 결과를 저장할 수 있습니다.

```json
[
  {
    "title": "AP sample article",
    "link": "https://apnews.com/article/example",
    "ticker": ["SPY"],
    "source": "AP News"
  }
]
```

```bash
python3 scripts/run_smoke_suite.py \
  --config smoke_suite.json \
  --output-dir results
```

생성 결과:

- 기사별 JSON 결과 파일
- `results/suite_summary.json`
- `results/suite_summary.md`

## Supabase 보안 잠금

Supabase Table Editor에서 `raw_news`, `raw_news_tickers`, `enrichment_jobs`,
`enrichment_results` 테이블이 `UNRESTRICTED` 로 보인다면, 테이블이 불필요한 것이
아니라 RLS/권한 정책이 느슨한 상태일 가능성이 큽니다.

이 테이블들은 현재 GenAI 파이프라인의 운영 테이블이므로 삭제하지 말고,
클라이언트 직접 접근만 차단하는 방향으로 잠그는 것을 권장합니다.

Supabase SQL Editor에서 아래 스크립트를 실행하면 됩니다.

```bash
scripts/supabase_lockdown_genai_tables.sql
```

이 스크립트는:

- `anon`, `authenticated` 역할의 직접 접근 권한을 제거하고
- GenAI 운영 테이블에 RLS를 활성화합니다

즉 FE/공개 클라이언트가 DB를 직접 읽지 못하게 하고, 서버/API를 통해서만
데이터를 노출하는 방향으로 정리하는 데 목적이 있습니다.

## 주요 환경변수

- `GENAI_DATABASE_BACKEND`
  - `sqlite` 또는 `postgres`
- `GENAI_POSTGRES_DSN`
  - `GENAI_DATABASE_BACKEND=postgres`일 때 필요
- `GENAI_SQLITE_DB_PATH`
  - SQLite 사용 시 선택
- `GENAI_WORKER_POLL_INTERVAL`
  - worker polling 간격
- `GENAI_ENABLE_JOB_PROCESS_API`
  - 웹 API에서 `process-next`를 허용할지 여부
- `GENAI_USE_WORKER_FOR_DIRECT_ENRICHMENT`
  - 직접 분석 API를 worker-backed 방식으로 처리할지 여부
- `GENAI_DIRECT_ENRICHMENT_WAIT_TIMEOUT`
  - 직접 분석 요청 대기 timeout
- `GEMINI_API_KEY` (또는 `GOOGLE_API_KEY`)
  - 제목, 3줄 요약, XAI 하이라이트의 UI용 한글 생성/번역에 사용
- `GEMINI_API_BASE_URL`
  - 기본값 `https://generativelanguage.googleapis.com/v1beta`
- `GENAI_FAIL_ON_SUSPICIOUS_GPU_RUNTIME`
  - 기본값 `false`
  - CPU 서비스에서 GPU 패키지 흔적(`nvidia-*`, `triton`, torch CUDA build)이 감지되면 웹/워커 시작을 차단
- `GENAI_DIRECT_ENRICHMENT_POLL_INTERVAL`
  - 직접 분석 요청 대기 polling 간격
- `BASIC_AUTH_USER`
- `BASIC_AUTH_PASSWORD`

Basic Auth를 켜면:

- `/health`와 `/health/deep`는 열려 있음
- `/`, `/docs`, `/openapi.json`, `/api/v1/*`, 정적 자산은 인증 필요

## 헬스 체크

### `GET /health`

가벼운 생존 확인용 엔드포인트입니다.

예시:

```json
{
  "status": "ok"
}
```

### `GET /health/deep`

DB 연결 여부까지 포함한 상세 점검 엔드포인트입니다.

예시:

```json
{
  "status": "ok",
  "database_backend": "postgres",
  "database_ok": true,
  "database_error": null,
  "guard_fail_on_suspicious_gpu_runtime": true,
  "runtime_torch_installed": true,
  "runtime_torch_cuda_version": null,
  "runtime_torch_cuda_available": false,
  "runtime_gpu_packages_detected": "",
  "runtime_suspicious_gpu_runtime": false
}
```

## 보안 주의사항

- `.env`, 비밀키, 토큰, DB 비밀번호는 절대 저장소에 커밋하지 마세요.
- 운영 secret은 GitHub가 아니라 배포 플랫폼 환경변수에만 저장하세요.
- public 저장소로 전환할 경우, 현재 파일뿐 아니라 과거 git history에도 secret이 없었는지 다시 확인하세요.
- `summary_text`나 `article_text`에 `EMPTY`, `N/A`, `NULL`, `NONE`, `-` 같은 placeholder를 넣으면 실제 텍스트가 아닌 빈값으로 처리됩니다.