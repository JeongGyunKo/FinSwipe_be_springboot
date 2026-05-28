# Financial News Gen AI Service API 명세서

문서 버전: `v1.0`  
작성 기준일: `2026-03-24`  
대상 독자: `PM / BE / 연동 담당자 / 운영 담당자`

## 1. 개요

본 문서는 현재 구현 기준의 Financial News Gen AI Service API 전체 명세서이다.  
주요 용도는 다음과 같다.

- BE 연동 기준 정의
- 입력/출력 필드 정의
- 상태값 및 실패값 정의
- 운영 시 health / job / result 조회 기준 정의

기본 경로:

- 웹: `/`
- Health: `/health`, `/health/deep`
- API Prefix: `/api/v1`

본 문서는 다음 질문에 바로 답할 수 있도록 작성되었다.

- 어떤 API를 호출해야 하는가
- 어떤 요청 JSON을 보내야 하는가
- 어떤 응답 JSON을 기대할 수 있는가
- 어떤 경우 실패로 처리되는가
- 운영 점검은 어떤 경로로 해야 하는가

---

## 2. 인증

기본 인증 방식:

- Basic Auth

인증 예외 경로:

- `GET /health`
- `GET /health/deep`
- `HEAD /` 내부 probe 용도

인증 실패 시:

- HTTP `401 Unauthorized`

BE 연동 시 유의사항:

- 운영/서버 간 호출은 기본적으로 Basic Auth를 포함해야 한다.
- Render 등 배포 플랫폼의 내부 헬스체크는 인증 예외 경로를 사용한다.

---

## 3. 공통 데이터 규칙

### 3.1 Placeholder 텍스트 처리

다음 값들은 실제 텍스트가 아닌 **빈값(None)** 으로 처리한다.

- `EMPTY`
- `N/A`
- `NA`
- `NONE`
- `NULL`
- `-`

즉 `summary_text="EMPTY"` 는 직접 제공 텍스트로 간주하지 않는다.

### 3.2 최소 텍스트 기준

현재 validation 기준:

- 최소 1단어 이상
- 최소 10자 이상

이 기준을 만족하지 못하면 `validate_failed`가 발생할 수 있다.

### 3.3 ticker 정규화

- 입력 ticker는 trim 후 대문자화
- 중복 제거

예:

- `[" aapl ", "AAPL", "msft"]` -> `["AAPL", "MSFT"]`

---

## 4. API 한눈에 보기

| 구분 | Method | Path | 용도 | 인증 |
|---|---|---|---|---|
| Web | `GET` | `/` | 내부 테스트용 웹 화면 | 필요 |
| Web | `HEAD` | `/` | 내부 probe | 예외 |
| Health | `GET` | `/health` | 경량 헬스체크 | 예외 |
| Health | `GET` | `/health/deep` | DB 포함 심화 헬스체크 | 예외 |
| Ingestion | `POST` | `/api/v1/news/intake` | 뉴스 메타데이터 저장 + job 생성 | 필요 |
| Ingestion | `POST` | `/api/v1/news/intake-text` | 직접 텍스트 저장 + job 생성 | 필요 |
| Ingestion | `GET` | `/api/v1/news/{news_id}` | raw/job/enrichment 저장 상태 조회 | 필요 |
| Ingestion | `GET` | `/api/v1/news/{news_id}/result` | 외부 소비용 최종 결과 조회 | 필요 |
| Worker | `POST` | `/api/v1/jobs/process-next` | 대기열 job 1건 처리 | 필요 |
| Ops | `GET` | `/api/v1/operations/stats` | 운영 통계 조회 | 필요 |
| Direct | `POST` | `/api/v1/articles/enrich` | 즉시 분석 실행(URL 또는 직접 텍스트) | 필요 |
| Direct | `POST` | `/api/v1/articles/enrich-text` | 즉시 분석 실행(직접 텍스트 필수) | 필요 |

---

## 5. 주요 Enum 정의

### 4.1 전체 결과 상태

- `pending`
- `processing`
- `completed`
- `partial`
- `failed`

### 4.2 저장 기준 분석 상태 (`analysis_status`)

- `pending`
- `fetch_failed`
- `clean_failed`
- `validate_failed`
- `summarize_failed`
- `sentiment_failed`
- `xai_failed`
- `mixed_detection_failed`
- `build_payload_failed`
- `persist_failed`
- `completed_with_partial_results`
- `completed`

### 4.3 전체 결과 outcome (`analysis_outcome` / `outcome`)

- `success`
- `partial_success`
- `fatal_failure`

### 4.4 Job 상태

- `queued`
- `retry_pending`
- `processing`
- `completed`
- `failed`

### 4.5 Sentiment Label

- 내부 FinBERT 기준:
  - `positive`
  - `neutral`
  - `negative`

- 외부 API 응답 기준:
  - `bullish`
  - `neutral`
  - `bearish`
  - `mixed`

### 4.6 Fetch 상태

- `success`
- `fetch_failed`
- `parse_failed`

### 4.7 Fetch Failure Category

- `invalid_url`
- `access_blocked`
- `rate_limited`
- `network_error`
- `ssl_error`
- `unsupported_content_type`
- `parse_error`
- `empty_extract`
- `unexpected_error`

### 4.8 Article Text Source

- `provided_article_text`
- `provided_summary_text`
- `json_ld`
- `generic_json`
- `paragraph_blocks`
- `container_block`
- `meta_description`
- `best_candidate`

---

## 6. 공통 요청 모델

### 5.1 `ArticleEnrichmentRequest`

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `news_id` | string | Y | 기사 고유 식별자 |
| `title` | string | Y | 기사 제목 |
| `link` | string(URL) | Y | 기사 원문 URL |
| `ticker` | string[] | N | 관련 종목 코드 목록 |
| `source` | string | N | 언론사 또는 소스명 |
| `published_at` | datetime | N | 발행 시각 |

### 5.2 `FlexibleTextEnrichmentRequest`

`ArticleEnrichmentRequest` + 아래 필드 추가

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `article_text` | string | N | 직접 제공 원문 |
| `summary_text` | string | N | 직접 제공 요약/스니펫 |

### 5.3 `DirectTextEnrichmentRequest`

`FlexibleTextEnrichmentRequest` 기반이며 아래 조건 필수:

- `article_text` 또는 `summary_text` 중 하나 이상 존재해야 함

---

## 7. 공통 응답 모델

### 6.1 `EnrichmentJobRecord`

| 필드 | 타입 | 설명 |
|---|---|---|
| `job_id` | string | job UUID |
| `news_id` | string | 기사 식별자 |
| `status` | enum | job 상태 |
| `attempts` | int | 현재 시도 횟수 |
| `max_attempts` | int | 최대 시도 횟수 |
| `last_error` | string \| null | 마지막 에러 메시지 |
| `last_analysis_status` | string \| null | 마지막 분석 상태 |
| `created_at` | datetime | 생성 시각 |
| `updated_at` | datetime | 갱신 시각 |
| `next_retry_at` | datetime \| null | 재시도 예정 시각 |
| `started_at` | datetime \| null | 처리 시작 시각 |
| `completed_at` | datetime \| null | 처리 완료 시각 |

### 6.2 `ArticleFetchResult`

| 필드 | 타입 | 설명 |
|---|---|---|
| `link` | string(URL) | 요청한 원문 URL |
| `publisher_domain` | string | 도메인 |
| `final_url` | string \| null | redirect 이후 최종 URL |
| `http_status_code` | int \| null | HTTP 상태코드 |
| `content_type` | string \| null | 응답 content-type |
| `extraction_source` | enum \| null | 텍스트 추출 방식 |
| `attempt_count` | int | fetch 시도 횟수 |
| `raw_text` | string | 원문/제공 텍스트 |
| `cleaned_text` | string | 정제 텍스트 |
| `fetch_status` | enum | fetch 결과 |
| `retryable` | bool | 재시도 가능 여부 |
| `failure_category` | enum \| null | 실패 분류 |
| `error_message` | string \| null | 에러 메시지 |

### 6.3 `ArticleEnrichmentResponse`

| 필드 | 타입 | 설명 |
|---|---|---|
| `news_id` | string | 기사 ID |
| `title` | string | 제목 |
| `link` | string(URL) | 기사 URL |
| `summary_3lines` | SummaryLine[] | 최대 3줄 요약 |
| `sentiment` | object \| null | 감성 결과 |
| `xai` | object \| null | 근거 문장/XAI |
| `mixed_flags` | object \| null | mixed/conflict 결과 |
| `status` | enum | 외부 API 전체 상태 |
| `outcome` | enum | 전체 성공/부분성공/치명실패 |
| `analyzed_at` | datetime | 분석 시각 |
| `error` | object \| null | 최상위 에러 |
| `stage_statuses` | object[] | 단계별 상태 |

---

## 8. 엔드포인트 명세

## 8.1 Web

### `GET /`

용도:

- 내부 테스트용 웹 UI HTML 반환

응답:

- `200 OK`
- `text/html`

### `HEAD /`

용도:

- 내부 probe

응답:

- `200 OK`

---

## 8.2 Health

### `GET /health`

용도:

- 경량 헬스체크

응답 예시:

```json
{
  "status": "ok"
}
```

### `GET /health/deep`

용도:

- DB 포함 심화 헬스체크

응답 예시:

```json
{
  "status": "ok",
  "database_backend": "sqlite",
  "database_ok": true,
  "database_error": null
}
```

가능한 `status`:

- `ok`
- `degraded`

---

## 8.3 Ingestion API

### `POST /api/v1/news/intake`

용도:

- raw news 메타데이터 저장
- enrichment job 생성

요청 바디:

```json
{
  "news_id": "news-001",
  "title": "Company beats earnings estimates",
  "link": "https://example.com/article/1",
  "ticker": ["AAPL"],
  "source": "Reuters",
  "published_at": "2026-03-24T09:00:00Z"
}
```

응답:

- `200 OK`

응답 예시:

```json
{
  "news_id": "news-001",
  "queued": true,
  "message": "Raw news metadata saved and enrichment job queued.",
  "job": {
    "job_id": "uuid",
    "news_id": "news-001",
    "status": "queued",
    "attempts": 0,
    "max_attempts": 3,
    "last_error": null,
    "last_analysis_status": null,
    "created_at": "2026-03-24T09:00:00Z",
    "updated_at": "2026-03-24T09:00:00Z",
    "next_retry_at": null,
    "started_at": null,
    "completed_at": null
  }
}
```

비고:

- 동일 기사에 활성 job(`queued`, `retry_pending`, `processing`)이 있으면 새 job 대신 기존 job 반환

### `POST /api/v1/news/intake-text`

용도:

- 직접 제공 텍스트 저장
- enrichment job 생성

요청 바디 예시:

```json
{
  "news_id": "news-002",
  "title": "Company guidance updated",
  "link": "https://example.com/article/2",
  "ticker": ["MSFT"],
  "source": "Internal",
  "summary_text": "Company raised guidance for next quarter."
}
```

추가 규칙:

- `article_text` 또는 `summary_text` 중 하나 이상 필요
- placeholder 문자열은 빈값으로 처리

응답:

- `200 OK`
- 구조는 `/news/intake` 와 동일

### `GET /api/v1/news/{news_id}`

용도:

- raw news + latest job + enrichment storage payload 조회

응답:

- `200 OK`
- 없으면 `404`

응답 구조:

```json
{
  "news_id": "news-001",
  "raw_news": {},
  "latest_job": {},
  "enrichment": {}
}
```

### `GET /api/v1/news/{news_id}/result`

용도:

- 외부 API 응답 형식 기준 최종 결과 조회

응답:

- `200 OK`
- 없으면 `404`

응답 구조:

```json
{
  "news_id": "news-001",
  "raw_news": {},
  "latest_job": {},
  "result": {}
}
```

### `POST /api/v1/jobs/process-next`

용도:

- 큐에 있는 enrichment job 1건 처리

응답 예시:

```json
{
  "processed": true,
  "retry_scheduled": false,
  "message": "Processed one enrichment job.",
  "news_id": "news-001",
  "job": {},
  "analysis_status": "completed",
  "analysis_outcome": "success",
  "enrichment": {}
}
```

비고:

- 큐가 비면 `processed=false`
- retryable fetch failure면 `retry_scheduled=true`

### `GET /api/v1/operations/stats`

용도:

- 운영 통계 조회

응답 예시:

```json
{
  "generated_at": "2026-03-24T09:00:00Z",
  "total_enrichment_results": 10,
  "total_jobs": 12,
  "total_fetch_failures": 2,
  "retryable_fetch_failures": 1,
  "job_status_counts": [],
  "analysis_status_counts": [],
  "extraction_source_counts": [],
  "fetch_failure_category_counts": [],
  "top_failure_domains": [],
  "publisher_outcomes": []
}
```

---

## 8.4 Direct Enrichment API

### `POST /api/v1/articles/enrich`

용도:

- URL 또는 직접 텍스트 기준 즉시 enrichment 수행

요청:

`FlexibleTextEnrichmentRequest`

예시:

```json
{
  "news_id": "news-003",
  "title": "Company announces new product",
  "link": "https://example.com/article/3",
  "ticker": ["NVDA"],
  "source": "Reuters"
}
```

직접 텍스트 포함 예시:

```json
{
  "news_id": "news-004",
  "title": "Licensed text sample",
  "link": "https://example.com/article/4",
  "ticker": ["TSLA"],
  "summary_text": "Company announced a new strategic partnership."
}
```

응답:

- `200 OK`
- `ArticleEnrichmentResponse`

### `POST /api/v1/articles/enrich-text`

용도:

- 반드시 직접 제공 텍스트 기반 즉시 enrichment 수행

요청:

`DirectTextEnrichmentRequest`

필수 조건:

- `article_text` 또는 `summary_text` 존재

응답:

- `200 OK`
- `ArticleEnrichmentResponse`

---

## 9. 상태/결과 해석 가이드

### 8.1 성공

- `status=completed`
- `outcome=success`

### 8.2 부분 성공

- 일부 단계 실패
- payload는 생성됨
- `outcome=partial_success`

### 8.3 치명 실패

- `outcome=fatal_failure`
- `analysis_status`에 실패 지점 반영

대표 예:

- `fetch_failed`
- `validate_failed`

---

## 10. 주요 실패 시나리오

### 9.1 Placeholder 잘못 전달

예:

- `summary_text = "EMPTY"`

현재 처리:

- placeholder는 빈값으로 정규화
- 직접 제공 텍스트로 처리하지 않음

### 9.2 텍스트가 너무 짧은 경우

- 현재 기준: 최소 1단어 + 10자
- 미달 시 `validate_failed`

### 9.3 원문 fetch 실패

- anti-bot, SSL, network, rate-limit, unsupported content-type 가능
- `fetch_failed`
- 일부는 retryable

---

## 11. PM / BE 전달 시 핵심 메모

- `POST /api/v1/news/intake`, `POST /api/v1/news/intake-text`는 저장 + 비동기 job 생성용이다.
- `POST /api/v1/articles/enrich`, `POST /api/v1/articles/enrich-text`는 요청 시점에 바로 분석 결과를 돌려주는 즉시 실행 API다.
- `GET /api/v1/news/{news_id}`는 내부 저장 상태 확인용이다.
- `GET /api/v1/news/{news_id}/result`는 외부 소비 관점의 최종 결과 조회용이다.
- `summary_text="EMPTY"` 같은 placeholder 값은 실제 텍스트가 아니라 빈값으로 처리된다.
- 현재 최소 validate 기준은 `1단어 + 10자`이다.
- 운영 헬스체크는 `/health`, 심화 점검은 `/health/deep`를 사용한다.

---

## 12. 제출/협업용 권장 문서 세트

실무상 아래 3개를 같이 제출하는 것이 좋다.

1. `docs/genai_spec.md`
2. `docs/api_spec.md`
3. `docs/ops_constraints.md`