# 미사용 엔드포인트 감사 (2026-06-25)

BE 컨트롤러 10개 전체 엔드포인트를 **FE 레포(`naangarchive/FinSwipe`) 실제 `fetch` 호출**,
**어드민 정적 페이지(`admin/digest/preview/card-preview.html`)**, **BE 내부 Java 호출**과 교차 대조한 결과.

> 상태: **분석만 완료, 코드 삭제는 보류.** 정리 시 이 문서를 기준으로 진행.

대조 방법:
- FE: `src/**` 의 `${VITE_API_BASE_URL}/...` fetch 경로 전수 추출
- 어드민: `be/src/main/resources/static/*.html` 의 엔드포인트 문자열 검색
- BE 내부: `be/src/main/java/**` 에서 해당 서비스 메서드 호출처 검색 (컨트롤러·테스트 제외)

---

## ① 제거 후보 — FE❌ · 어드민❌ · BE 내부❌ (완전 고아)

| 엔드포인트 | 비고 |
|---|---|
| `POST /auth/find-login-id` | FE엔 "이메일 찾기"(`find-email`)만 존재, "아이디 찾기" 화면 없음 |
| `GET /news/search` | 검색 UI 미출시 (NVDA 따옴표 버그는 고쳤으나 FE 미연동) |
| `DELETE /news/device-token` | FE는 `POST`만 사용 (로그아웃 시 토큰 해제 미구현) |
| `GET /quiz/sessions/{sessionId}` | FE는 POST 플로우만 사용, 세션 조회 안 함 |
| `POST /analysis/personalized` | 클라이언트 0. GenAI 단순 프록시 |
| `POST /analysis/curate` | 클라이언트 0. GenAI 단순 프록시 |
| `POST /analysis/coach` | 클라이언트 0. GenAI 단순 프록시 (학습코치 FE 미연동) |
| `GET /news/genai/health` | 어떤 화면도 호출 안 함 |
| `GET /admin/guardrail` | `GuardrailController` 전체가 어떤 정적 페이지에서도 호출 안 됨 (Swagger 전용) |

> ⚠️ `analysis/personalized·curate·coach`를 BE에서 지우면 GenAI(별개 레포)의 동일 엔드포인트가 고립됨 → 제품 결정 필요.

## ② FE 미연동 — "기능 누락" 의심 (지우기 전 FE 로드맵 확인)

| 엔드포인트 | 상황 |
|---|---|
| `POST /user/level` | FE `Quiz.tsx`는 완료 후 tendency만 표시·홈 이동, **레벨/성향을 저장 안 함** → 실제 영속화 갭 가능성 |
| `GET /chat/alerts/unread` | 미읽음 알림 뱃지용. BE 구현됐으나 FE 뱃지 미연동 |
| `GET /analysis/ticker-timeline` | 커밋 `c58589c`에서 FE 핸드오프용 신규 추가, 아직 미연동. `TickerTimelineService`는 `/admin/ticker-timeline`과 공유 → **서비스는 유지 필수** |

→ 죽은 코드 아님 / "FE 작업 대기 중". 결정 보류(2026-06-25 기준).

## ③ 유지 — 어드민 정적 페이지가 사용 중 (메인 FE는 미사용)

`/admin/users`, `/admin/user-digest`, `/admin/ticker-timeline`, `/admin/metrics`,
`/news/tickers/{ticker}/sentiment-trend`, `/news/collect`, `/news/reanalyze`,
`/news/jobs/{jobId}`, `/news/test`
— admin.html·digest.html·preview.html·card-preview.html가 호출.

## ④ 운영/디버그 수동 트리거 — 클라이언트 없음, curl 전용 (정리 판단)

| 엔드포인트 | 판단 |
|---|---|
| `POST /news/reset-insights`, `POST /news/analyze`, `GET /news/analyze/latest`, `POST /news/diagnose` | 수동 ops/디버그. admin.html 버튼 없으면 정리 가능 |
| `DELETE /admin/cleanup-bae` | BA/BAE 버그 이미 해결 → 일회성 잔재, 제거 가능 |
| `POST /admin/trigger/delisting-check` | 상장폐지 수동 트리거. 스케줄러 보조용 |

---

## FE가 실제 사용하는 엔드포인트 (참고, 23개)

`POST /auth/register·login·google·forgot-password·reset-password·find-email`,
`GET /auth/check-email·check-login-id·verify-email`,
`GET·PATCH /user/profile`, `GET·PUT /user/tickers`, `PUT /user/news-sort`,
`GET /news/latest`, `POST /news/{id}/read`, `GET /news/article/{id}`, `GET /news/tickers`,
`POST /news/device-token`, `GET·PUT /news/notification-settings`,
`POST /chat/message`, `GET /chat/messages`,
`POST /quiz/sessions`, `POST /quiz/sessions/{id}/next-question`, `POST /quiz/sessions/{id}/answers`,
`POST /analysis/digest`

---

## 권장 정리 순서 (실행 시)

1. **저위험 즉시 삭제**: ① 중 `find-login-id`·`news/search`·`DELETE device-token`·`GET quiz/sessions/{id}`·`genai/health`·`GuardrailController`·`admin/cleanup-bae` → 핸들러 + 고아 서비스 메서드 동반 제거
2. **제품 확인 후 삭제**: `analysis/personalized·curate·coach` (GenAI 프록시)
3. **FE 확인 필요(보류)**: `user/level`·`chat/alerts/unread`·`analysis/ticker-timeline`
