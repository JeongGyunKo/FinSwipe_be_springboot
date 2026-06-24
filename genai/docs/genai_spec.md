# Financial News Gen AI 명세서

## 1. 목적

본 서비스는 금융 뉴스 기사 또는 기사 요약 텍스트를 입력받아 아래 결과를 생성하는 Gen AI 서비스이다.

- 3줄 요약
- 기사 감성 분석
- 감성 근거(XAI) 추출
- 혼합 신호(mixed/conflict) 탐지
- 처리 상태 및 실패 사유 추적

본 서비스는 백엔드(BE)에서 호출하는 내부 API를 기준으로 동작한다.

## 2. 입력

공통 입력 필드:

- `news_id`: 기사 고유 식별자
- `title`: 기사 제목
- `link`: 기사 URL
- `ticker`: 관련 종목 코드 목록
- `source`: 언론사 또는 원천 소스
- `published_at`: 기사 발행 시각

직접 텍스트 제공 시 추가 입력:

- `article_text`: 라이선스 보유 원문
- `summary_text`: 라이선스 보유 요약/스니펫 텍스트

## 3. 처리 방식

서비스는 입력 형태에 따라 두 경로로 동작한다.

### 3.1 URL 기반 분석

- `article_text`, `summary_text`가 없으면 URL을 기반으로 원문 fetch 수행
- fetch 성공 시 텍스트 정제(clean)
- 정제 후 유효성 검증(validate)
- 통과 시 요약, 감성 분석, XAI, mixed 탐지 수행

### 3.2 직접 텍스트 기반 분석

- `article_text` 또는 `summary_text`가 있으면 제공 텍스트를 우선 사용
- 이 경우 원문 fetch를 생략할 수 있음
- 이후 clean, validate, summarize, sentiment, xai, mixed 탐지를 동일하게 수행

## 4. Placeholder 처리 규칙

다음 값은 실제 텍스트가 아니라 **빈값(None)** 으로 처리한다.

- `EMPTY`
- `N/A`
- `NA`
- `NONE`
- `NULL`
- `-`

즉 위 값이 들어오면 “직접 제공 텍스트가 있다”고 보지 않는다.

## 5. 최소 텍스트 유효성 기준

현재 validate 기준:

- 최소 **1단어 이상**
- 최소 **10자 이상**

위 기준을 만족하지 못하면 `validate_failed`가 발생할 수 있다.

주의:

- 이번에 수정한 버그의 직접 원인은 “최소 길이 제한” 자체가 아니라,
  `EMPTY` 같은 placeholder 문자열을 실제 텍스트로 잘못 처리하던 점이었다.
- 현재는 placeholder 정규화가 적용되어, 해당 값은 직접 제공 텍스트로 취급되지 않는다.

## 6. 출력

주요 출력 항목:

- `summary_3lines`: 최대 3개의 요약 문장
- `sentiment`: `bullish`, `bearish`, `mixed`, `neutral`
- `xai`: 감성 판단 근거 문장/구간
- `mixed_flags`: 상충 신호 여부
- `status`: `pending`, `processing`, `completed`, `partial`, `failed`
- `outcome`: `success`, `partial_success`, `fatal_failure`
- `stage_statuses`: 단계별 처리 상태
- `error`: 최상위 에러 정보

## 7. 내부 처리 단계

파이프라인 단계:

1. `fetch`
2. `clean`
3. `validate`
4. `summarize`
5. `sentiment`
6. `xai`
7. `mixed_detection`
8. `build_payload`
9. `persist`

## 8. 실패 상태 정의

대표 상태:

- `fetch_failed`: 원문 수집 실패
- `clean_failed`: 텍스트 정제 실패
- `validate_failed`: 길이/품질 기준 미달
- `summarize_failed`: 요약 실패
- `sentiment_failed`: 감성 분석 실패
- `xai_failed`: 설명 가능성 추출 실패
- `mixed_detection_failed`: mixed 탐지 실패
- `persist_failed`: 저장 실패
- `completed_with_partial_results`: 일부 단계 실패 포함 완료
- `completed`: 정상 완료

## 9. 모델/엔진

현재 파이프라인 구성:

- 감성 분석: FinBERT (`ProsusAI/finbert`) 로컬 모델 — Positive / Negative / Neutral 분류 + 혼합(mixed) 신호 감지
- 설명 가능성(XAI): FinBERT 어텐션 기반 sentence-level explanation — 마지막 레이어 [CLS] 어텐션을 토큰→문장 단위로 집계해 근거 문장 하이라이트 (explanation_method: `attention_sentence`)
- 요약 · 번역 · 개인화 · 챗봇 · 퀴즈 코치: Gemini (`gemini-2.5-flash-lite`)
- 기술 지표: yfinance 기반 RSI(14) · MACD(12/26/9) · 거래량 비율

## 10. 제약 및 해석 주의사항

- 매우 짧은 텍스트는 형식상 통과하더라도 분석 품질이 낮을 수 있다.
- URL fetch 결과에 따라 기사 본문 확보 여부가 달라질 수 있다.
- XAI는 로컬 근사(local explanation)이며, 모델 판단의 절대적 근거를 의미하지 않는다.