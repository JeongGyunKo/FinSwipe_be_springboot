# Financial News Gen AI 운영 / 제약 명세서

## 1. 서비스 가용성 기준

### 경량 헬스체크

- `GET /health`
- DB 접근 없이 즉시 `200` 반환
- 배포 플랫폼(Render) 헬스체크 용도

### 심화 헬스체크

- `GET /health/deep`
- DB 접근 포함
- 내부 운영 점검 용도

## 2. 입력 제약

### 직접 텍스트 입력

- `article_text` 또는 `summary_text` 중 하나 이상 필요
- placeholder 값은 텍스트로 보지 않음

placeholder 목록:

- `EMPTY`
- `N/A`
- `NA`
- `NONE`
- `NULL`
- `-`

### 최소 텍스트 기준

현재 validate 기준:

- 최소 1단어
- 최소 10자

주의:

- 이 기준은 “형식상 통과 최소선”이다.
- 실제 모델 품질 관점에서는 더 긴 텍스트가 유리하다.

## 3. 실패 해석 기준

### `fetch_failed`

- 원문 수집 실패
- 도메인 차단, anti-bot, timeout 등 가능

### `validate_failed`

- 정제 후 텍스트 길이/형식 기준 미달
- 너무 짧거나 실질적으로 분석 불가한 경우

### `completed_with_partial_results`

- 일부 단계는 실패했지만 payload는 저장된 경우

## 4. 이번 수정으로 반영된 사항

### 수정 1. Placeholder 오인식 방지

기존 문제:

- `summary_text="EMPTY"` 같은 값이 실제 제공 텍스트로 간주됨
- 원문 fetch를 건너뛰고 그대로 분석하려다 `validate_failed` 발생 가능

현재 상태:

- placeholder 값은 빈값으로 정규화됨
- 더 이상 직접 제공 텍스트로 처리되지 않음

### 수정 2. 최소 길이 완화

BE 요청 반영:

- 기존: 30단어 + 200자
- 현재: 1단어 + 10자

## 5. 운영상 주의할 점

- 10자 수준 텍스트는 validation은 통과할 수 있어도, 분석 품질은 낮을 수 있다.
- 직접 텍스트가 부실하면 요약, sentiment, XAI 품질이 떨어질 수 있다.
- 가능하면 summary보다는 원문 또는 더 긴 본문 텍스트 제공이 권장된다.

## 6. 재시도 정책

- fetch 실패 중 retryable한 경우 job은 `retry_pending`으로 재큐잉 가능
- retry 불가이거나 최대 재시도 초과 시 `failed`

## 7. 배포 관련 메모

- 배포 플랫폼 헬스체크는 `/health` 기준 사용 권장
- `/health/deep`는 운영 점검용으로 사용
- 무거운 초기화는 startup blocking 경로에 두지 않는 것이 안전함