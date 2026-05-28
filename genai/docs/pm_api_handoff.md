# Financial News Gen AI 서비스 명세서 (PM 공유용)

문서 버전: `v1.0`  
작성 기준일: `2026-03-24`  
대상: `PM / BE / 연동 담당자 / 운영 담당자`

---

## 1. 문서 목적

본 문서는 Financial News Gen AI 서비스의 현재 구현 기준을 PM과 연동 담당자가 빠르게 이해할 수 있도록 정리한 문서이다.

이 문서에서 확인할 수 있는 내용은 다음과 같다.

- 서비스가 어떤 역할을 하는지
- 어떤 API를 제공하는지
- 각 API가 언제 사용되는지
- 요청/응답 형식이 어떻게 되는지
- 어떤 상태값과 실패값이 존재하는지
- 운영 시 어떤 점을 주의해야 하는지

---

## 2. 서비스 개요

본 서비스는 금융 뉴스 기사 또는 직접 제공된 텍스트를 입력받아 아래 결과를 생성하는 내부 Gen AI 서비스이다.

- 3줄 요약
- 감성 분석
- 감성 판단 근거(XAI)
- mixed / conflict 신호 탐지
- 처리 상태 및 실패 사유 추적

서비스는 크게 두 가지 방식으로 사용할 수 있다.

1. **비동기 Job 기반 처리**
   - 뉴스 메타데이터 또는 직접 텍스트를 저장
   - enrichment job 생성
   - 이후 상태/결과 조회
2. **즉시 실행 처리**
   - 요청 시점에 바로 분석 수행
   - 요청 응답으로 결과 반환

---

## 3. Base URL 및 인증

### 3.1 Base URL

- Production URL은 배포 환경(Render) 기준 서비스 URL 사용
- API Prefix는 `/api/v1`

### 3.2 인증

- 기본 인증 방식: **Basic Auth**

### 3.3 인증 예외 경로

- `GET /health`
- `GET /health/deep`
- `HEAD /`

### 3.4 인증 실패 시

- `401 Unauthorized`

---

## 4. 공통 처리 규칙

### 4.1 Placeholder 텍스트 처리

아래 값은 실제 기사 텍스트가 아니라 **빈값(None)** 으로 처리한다.

- `EMPTY`
- `N/A`
- `NA`
- `NONE`
- `NULL`
- `-`

예를 들어 `summary_text = "EMPTY"` 는 “직접 제공 텍스트가 있다”로 보지 않는다.

### 4.2 최소 텍스트 기준

현재 validate 기준:

- 최소 **1단어 이상**
- 최소 **10자 이상**

이 기준을 만족하지 못하면 `validate_failed`가 발생할 수 있다.

참고:

- 이 기준은 “형식상 통과 최소선”이다.
- 실제 분석 품질은 텍스트가 더 길수록 안정적이다.

### 4.3 ticker 정규화

- trim 후 대문자 변환
- 중복 제거

예:

- `[" aapl ", "AAPL", "msft"]` -> `["AAPL", "MSFT"]`

### 4.4 날짜/시간 형식

- ISO 8601 UTC 기준 사용

예:

- `2026-03-24T09:00:00Z`

---

## 5. 처리 흐름

### 5.1 URL 기반 처리

직접 텍스트(`article_text`, `summary_text`)가 없으면:

1. 기사 URL 기준 원문 fetch
2. 텍스트 정제(clean)
3. 유효성 검증(validate)
4. 요약
5. 감성 분석
6. XAI
7. mixed 탐지
8. 결과 저장

### 5.2 직접 텍스트 기반 처리

`article_text` 또는 `summary_text`가 있으면:

1. 제공 텍스트 우선 사용
2. 필요 시 원문 fetch 생략
3. clean
4. validate
5. summarize
6. sentiment
7. xai
8. mixed detection
9. 결과 저장

---

## 6. API 한눈에 보기

| 구분 | Method | Path | 설명 | 인증 |
|---|---|---|---|---|
| Web | `GET` | `/` | 내부 테스트용 웹 화면 | 필요 |
| Web | `HEAD` | `/` | 내부 probe | 예외 |
| Health | `GET` | `/health` | 경량 헬스체크 | 예외 |
| Health | `GET` | `/health/deep` | DB 포함 심화 헬스체크 | 예외 |
| Ingestion | `POST` | `/api/v1/news/intake` | 뉴스 메타데이터 저장 + job 생성 | 필요 |
| Ingestion | `POST` | `/api/v1/news/intake-text` | 직접 텍스트 저장 + job 생성 | 필요 |
| Ingestion | `GET` | `/api/v1/news/{news_id}` | raw/job/enrichment 상태 조회 | 필요 |
| Ingestion | `GET` | `/api/v1/news/{news_id}/result` | 외부 소비용 최종 결과 조회 | 필요 |
| Worker | `POST` | `/api/v1/jobs/process-next` | 대기열 job 1건 처리 | 필요 |
| Ops | `GET` | `/api/v1/operations/stats` | 운영 통계 조회 | 필요 |
| Direct | `POST` | `/api/v1/articles/enrich` | 즉시 분석 실행(URL 또는 직접 텍스트) | 필요 |
| Direct | `POST` | `/api/v1/articles/enrich-text` | 즉시 분석 실행(직접 텍스트 필수) | 필요 |

---

## 7. 엔드포인트 상세

## 7.1 `GET /health`

### 목적

- 배포 플랫폼(Render) 및 기본 가용성 확인용 경량 헬스체크

### 특징

- DB 접근 없이 즉시 `200` 반환

### 응답 예시

```json
{
  "status": "ok"
}
```

---

## 7.2 `GET /health/deep`

### 목적

- DB 연결 상태를 포함한 심화 헬스체크

### 응답 예시

```json
{
  "status": "ok",
  "database_backend": "sqlite",
  "database_ok": true,
  "database_error": null
}
```

### 상태 해석

- `status=ok`: 애플리케이션 및 DB 상태 양호
- `status=degraded`: 애플리케이션은 살아 있으나 DB 문제가 있음

---

## 7.3 `POST /api/v1/news/intake`

### 목적

- 뉴스 메타데이터를 저장하고 enrichment job을 생성한다.

### 사용 시점

- 기사 원문은 URL로 추후 수집해도 되는 경우
- 우선 뉴스 식별자/제목/링크 중심으로 큐를 적재하고 싶은 경우

### Request Body

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `news_id` | string | Y | 기사 고유 ID |
| `title` | string | Y | 기사 제목 |
| `link` | string(URL) | Y | 기사 URL |
| `ticker` | array[string] | N | 종목 코드 목록 |
| `source` | string | N | 기사 출처 |
| `published_at` | datetime | N | 발행 시각 |

### 요청 예시

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

### 응답 예시

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

### 상태코드

- `200 OK`
- `401 Unauthorized`
- `422 Validation Error`

### 비고

- 동일 기사에 활성 job(`queued`, `retry_pending`, `processing`)이 있으면 새 job 대신 기존 job을 반환할 수 있다.

---

## 7.4 `POST /api/v1/news/intake-text`

### 목적

- 직접 제공된 원문 또는 요약 텍스트를 저장하고 enrichment job을 생성한다.

### 사용 시점

- 라이선스 보유 텍스트를 BE가 직접 전달하는 경우
- 외부 원문 fetch를 반드시 신뢰하지 않아도 되는 경우

### Request Body

`/api/v1/news/intake` 공통 필드 + 아래 필드 추가

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `article_text` | string | N | 직접 제공 원문 |
| `summary_text` | string | N | 직접 제공 요약/스니펫 |

### 추가 규칙

- `article_text` 또는 `summary_text` 중 하나 이상 필요
- placeholder 값은 실제 텍스트로 보지 않음

### 요청 예시

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

### 응답 예시

```json
{
  "news_id": "news-002",
  "queued": true,
  "message": "Raw news metadata saved and enrichment job queued.",
  "job": {
    "job_id": "uuid",
    "status": "queued"
  }
}
```

### 상태코드

- `200 OK`
- `401 Unauthorized`
- `422 Validation Error`

---

## 7.5 `GET /api/v1/news/{news_id}`

### 목적

- 특정 기사에 대한 저장 상태를 확인한다.

### 사용 시점

- ingestion 이후 현재 상태 확인
- raw news 저장 여부, latest job 상태, enrichment 저장 여부 확인

### Path Parameter

| 필드 | 타입 | 설명 |
|---|---|---|
| `news_id` | string | 기사 고유 ID |

### 응답 예시

```json
{
  "news_id": "news-001",
  "raw_news": {},
  "latest_job": {},
  "enrichment": {}
}
```

### 상태코드

- `200 OK`
- `401 Unauthorized`
- `404 Not Found`

---

## 7.6 `GET /api/v1/news/{news_id}/result`

### 목적

- 외부 소비 기준 최종 결과를 조회한다.

### 사용 시점

- FE/BE/운영에서 최종 분석 결과를 확인하는 경우

### 응답 예시

```json
{
  "news_id": "news-001",
  "raw_news": {},
  "latest_job": {},
  "result": {}
}
```

### 상태코드

- `200 OK`
- `401 Unauthorized`
- `404 Not Found`

---

## 7.7 `POST /api/v1/jobs/process-next`

### 목적

- 대기열에 있는 enrichment job 1건을 처리한다.

### 사용 시점

- 워커/스케줄러/운영자 수동 실행

### 응답 예시

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

### 상태코드

- `200 OK`
- `401 Unauthorized`

### 비고

- 큐가 비어 있으면 `processed=false`
- retryable한 실패는 `retry_scheduled=true`로 재시도 예정 상태가 될 수 있다

---

## 7.8 `GET /api/v1/operations/stats`

### 목적

- 운영 통계 및 처리 현황을 조회한다.

### 응답 예시

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

### 상태코드

- `200 OK`
- `401 Unauthorized`

---

## 7.9 `POST /api/v1/articles/enrich`

### 목적

- URL 또는 직접 텍스트 기준 즉시 분석을 수행하고 결과를 반환한다.

### 사용 시점

- 저장/큐 적재 없이 즉시 결과가 필요한 경우

### Request Body

| 필드 | 타입 | 필수 | 설명 |
|---|---|---:|---|
| `news_id` | string | Y | 기사 고유 ID |
| `title` | string | Y | 기사 제목 |
| `link` | string(URL) | Y | 기사 URL |
| `ticker` | array[string] | N | 종목 코드 목록 |
| `source` | string | N | 기사 출처 |
| `published_at` | datetime | N | 발행 시각 |
| `article_text` | string | N | 직접 제공 원문 |
| `summary_text` | string | N | 직접 제공 요약 |

### 요청 예시 (URL 기반)

```json
{
  "news_id": "news-003",
  "title": "Company announces new product",
  "link": "https://example.com/article/3",
  "ticker": ["NVDA"],
  "source": "Reuters"
}
```

### 요청 예시 (직접 텍스트 포함)

```json
{
  "news_id": "news-004",
  "title": "Licensed text sample",
  "link": "https://example.com/article/4",
  "ticker": ["TSLA"],
  "summary_text": "Company announced a new strategic partnership."
}
```

### 응답 예시

```json
{
  "news_id": "news-003",
  "title": "Company announces new product",
  "link": "https://example.com/article/3",
  "summary_3lines": [],
  "sentiment": null,
  "xai": null,
  "mixed_flags": null,
  "status": "completed",
  "outcome": "success",
  "analyzed_at": "2026-03-24T09:00:00Z",
  "error": null,
  "stage_statuses": []
}
```

### 상태코드

- `200 OK`
- `401 Unauthorized`
- `422 Validation Error`

---

## 7.10 `POST /api/v1/articles/enrich-text`

### 목적

- 반드시 직접 제공된 텍스트를 기준으로 즉시 분석을 수행한다.

### 추가 규칙

- `article_text` 또는 `summary_text` 중 하나 이상 필수

### 요청 예시

```json
{
  "news_id": "news-005",
  "title": "Licensed article sample",
  "link": "https://example.com/article/5",
  "ticker": ["AAPL"],
  "article_text": "Apple announced a new financing strategy and updated revenue guidance."
}
```

### 응답

- `200 OK`
- 응답 구조는 `POST /api/v1/articles/enrich` 와 동일

---

## 8. 주요 상태값 정의

### 8.1 외부 결과 상태 (`status`)

- `pending`
- `processing`
- `completed`
- `partial`
- `failed`

### 8.2 내부 분석 상태 (`analysis_status`)

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

### 8.3 전체 결과 (`outcome`)

- `success`
- `partial_success`
- `fatal_failure`

### 8.4 Job 상태

- `queued`
- `retry_pending`
- `processing`
- `completed`
- `failed`

---

## 9. 주요 실패 시나리오

## 9.1 `fetch_failed`

의미:

- 원문 수집 실패

가능한 원인:

- anti-bot 차단
- 도메인 접근 차단
- SSL 오류
- timeout
- rate limit
- unsupported content-type

## 9.2 `validate_failed`

의미:

- 텍스트 길이/형식이 분석 기준에 미달

예:

- 텍스트가 너무 짧음
- placeholder만 들어옴
- 실질적으로 분석 불가한 수준

## 9.3 `completed_with_partial_results`

의미:

- 일부 단계는 실패했지만 최종 payload 저장까지는 완료

---

## 10. 이번 반영 사항

이번 문서 기준으로 반영된 주요 수정은 다음과 같다.

### 10.1 Placeholder 오인식 방지

기존 문제:

- `summary_text="EMPTY"` 같은 값이 실제 제공 텍스트로 간주됨
- 원문 fetch를 건너뛰고 그대로 분석하려다 `validate_failed` 발생 가능

현재 상태:

- placeholder 값은 빈값으로 정규화됨
- 더 이상 직접 제공 텍스트로 처리되지 않음

### 10.2 최소 길이 완화

기존:

- `30단어 + 200자`

현재:

- `1단어 + 10자`

### 10.3 Health Check 경량화

- `/health`는 DB 접근 없이 즉시 `200`
- `/health/deep`는 DB 포함 점검

---

## 11. 운영 시 주의사항

- 매우 짧은 텍스트는 validation은 통과해도 분석 품질이 낮을 수 있다.
- 가능하면 `summary_text`보다 `article_text` 또는 원문 fetch가 더 안정적이다.
- 배포 플랫폼 헬스체크는 `/health`를 사용한다.
- `/health/deep`는 운영자용 심화 점검 경로이다.

---

## 12. PM / BE 공유 시 핵심 메시지

- 이 서비스는 **비동기 큐 처리 API**와 **즉시 분석 API**를 모두 제공한다.
- 직접 제공 텍스트가 없으면 URL 기반 원문 fetch를 수행한다.
- placeholder 값(`EMPTY`, `N/A` 등)은 이제 실제 텍스트로 처리되지 않는다.
- 현재 텍스트 validate 최소 기준은 `1단어 + 10자`이다.
- 분석 결과는 상태(`status`)와 결과(`outcome`), 단계별 상태(`stage_statuses`)로 해석해야 한다.

---

## 13. 첨부 문서

- `docs/api_spec.md`
- `docs/genai_spec.md`
- `docs/ops_constraints.md`
- `docs/openapi.yaml`
- `docs/openapi.json`