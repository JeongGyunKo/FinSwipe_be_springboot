# 다이제스트 요약 개편 — FE 핸드오프

> 일일 다이제스트의 "요약" 화면을 **텍스트 한 덩어리 → 구조화 카드**로 개편합니다.
> 하루 뉴스 인사이트를 ① 한 줄 평결+신호 칩 ② 거래일별 흐름(멀티데이) ③ 어제→오늘 상세 ④ 감성별 뉴스 로 종합합니다.
> 시각 레퍼런스: 같이 보낸 `digest-summary-preview.html` 를 브라우저로 열어 보세요 (실제 렌더 로직 + 샘플 데이터).

---

## 0. TL;DR (FE가 할 일)

1. **`DigestItem` 타입에 `sections`·`news_articles` 추가** — 응답엔 이미 오는데 현재 타입(`src/types/digest.ts`)이 누락. 기존 `summary`(덩어리)는 폴백용으로만.
2. **`DigestCard`(`src/components/briefing/CardDeck.tsx`) 리디자인** — 아래 §3 디자인대로.
3. **신규 엔드포인트 연동**: `GET /analysis/ticker-timeline?ticker=&sessions=5` (JWT) — 거래일별 멀티데이 흐름.

API/데이터는 모두 준비·배포 완료. FE는 화면만 바꾸면 됩니다.

---

## 0-1. `digest.html`이 쓰는 엔드포인트 ↔ FE 앱이 쓸 엔드포인트

> `digest.html`은 **어드민 미리보기 도구**라 `X-Admin-Key` 헤더 + 명시적 `user_id`로 **어드민 엔드포인트**를 호출합니다.
> **FE 앱은 이 어드민 엔드포인트를 쓰면 안 되고**, 아래 JWT 버전을 쓰면 됩니다. **응답 shape은 100% 동일** (내부적으로 같은 GenAI 호출).

| digest.html 호출 (어드민) | 인증 | FE 앱이 쓸 것 (JWT) | 응답 |
|---|---|---|---|
| `GET /admin/users` | `X-Admin-Key` | **불필요** — 유저 이름 표시용. FE는 자기 자신 | — |
| `POST /admin/user-digest`<br>body `{ "user_id": "..." }` | `X-Admin-Key` | **`POST /analysis/digest`**<br>body 불필요 (토큰에서 user 해석) | **동일** `{ digests[], user_level, user_tendency, generated_at }` |
| `GET /admin/ticker-timeline?ticker=&sessions=5` | `X-Admin-Key` | **`GET /analysis/ticker-timeline?ticker=&sessions=5`** | **동일** `{ ticker, sessions[] }` |

즉 FE가 실제로 연동할 엔드포인트는 **2개**: `POST /analysis/digest`(요약 본체) + `GET /analysis/ticker-timeline`(거래일 흐름). 상세 필드는 아래 §1.

> 참고: `digest.html`은 목업이 아니라 위 어드민 API 실데이터를 그대로 렌더합니다. 화면에 보인 `어제의_핵심/주가_반응/오늘_전망`은 응답의 `sections` 필드입니다(하드코딩 아님). FE 타입(`src/types/digest.ts`)에 `sections`가 없어 "API에 없는 것처럼" 보였던 것 — §2에서 추가.

---

## 1. API

### A. 다이제스트 (기존 — 변경 없음, 단 안 쓰던 필드 사용)
```
POST /analysis/digest         (JWT 필요, userId는 토큰에서 해석)
→ 200 { digests: DigestItem[], user_level, user_tendency, generated_at }
```
`DigestItem` **전체** 필드 (★ = 현재 FE 타입에 없음, 이번에 추가):

| 필드 | 타입 | 설명 |
|---|---|---|
| `ticker` | string | 종목 |
| `articles_count` | number | 분석 기사 수 |
| `sentiment_overview` | `{ positive, negative, neutral, avg_score }` | 감성 종합. `avg_score`는 -1~1 |
| `summary` | string | (구) 3단을 합친 한 덩어리 — **폴백용으로만** |
| ★ `sections` | `{ 어제의_핵심, 주가_반응, 오늘_전망 }` | 어제 마감 이후→오늘까지 3단 서술. **핵심 신규** |
| ★ `news_articles` | `Article[]` | 당일(24h) 대표 기사 최대 5건 |
| `technical_indicators` | `{ current_price, change_pct_1d, change_pct_1m, volume_ratio, RSI, RSI_signal, MACD:{macd,signal,histogram,trend} }` | 지표 |

`Article`: `{ headline_ko, headline, sentiment_label('positive'|'negative'|'neutral'), sentiment_score, published_at }`

### B. 거래일별 타임라인 (신규 · JWT)
```
GET /analysis/ticker-timeline?ticker=NVDA&sessions=5     (JWT 필요)
```
- 기사를 **미국 거래 세션(16:00 ET 마감) 단위**로 묶어 최근 N개 세션 반환 (DST·주말·휴장 자동 처리)
- 한국시간 혼선 방지: **라벨은 미국 거래일**. "오늘자"=직전 마감→다음 마감 진행중 세션
- `sessions`: 1~10, 기본 5. 응답 `sessions`는 **과거→오늘 오름차순**(마지막이 오늘자)

```jsonc
{
  "ticker": "NVDA",
  "sessions": [
    { "date": "2026-06-23", "label": "6/23", "count": 50,
      "sentiment": "neutral", "avgScore": 0.04,
      "articles": [ { "headlineKo": "...", "sentimentLabel": "neutral", "sentimentScore": 0.12 } ] },
    { "date": "2026-06-24", "label": "6/24", "count": 73, "sentiment": "neutral", "avgScore": -0.05, "articles": [ ... ] },
    { "date": "2026-06-25", "label": "6/25", "count": 11, "sentiment": "positive", "avgScore": 0.31, "articles": [ ... ] }
  ]
}
```
세션이 1개뿐이면(신규 상장 등) 이 섹션은 생략 권장 — 아래 "어제→오늘 흐름"이 커버.

---

## 2. TypeScript 타입 (추가/수정)

```ts
// src/types/digest.ts — DigestItem 에 추가
export interface DigestArticle {
  headline_ko?: string | null;
  headline?: string | null;
  sentiment_label: 'positive' | 'negative' | 'neutral';
  sentiment_score?: number | null;   // -1 ~ 1 (표시 시 ×100)
  published_at?: string | null;
}
export interface DigestSections {
  어제의_핵심?: string;
  주가_반응?: string;
  오늘_전망?: string;
}
export interface DigestItem {
  /* ...기존 필드... */
  summary: string;
  sections?: DigestSections | null;     // ★ 추가
  news_articles?: DigestArticle[];      // ★ 추가
}

// 신규 — 거래일 타임라인
export interface TimelineSession {
  date: string;        // 미국 거래일 ISO (예: "2026-06-25")
  label: string;       // "6/25"
  count: number;
  sentiment: 'positive' | 'negative' | 'neutral';
  avgScore: number;
  articles: { headlineKo?: string | null; sentimentLabel: string; sentimentScore?: number | null }[];
}
export interface TickerTimeline { ticker: string; sessions: TimelineSession[]; }
```

---

## 3. 디자인 명세 (요약 화면 구성)

위→아래 4블록. 라이트 테마. (정확한 마크업·CSS·계산 로직은 `digest-summary-preview.html` 참고)

### ① 오늘 한마디 — 신호 평결 카드
- **한 줄 평결**: 감성(avg_score)×주가(change_pct_1d) 조합으로 생성. 예:
  - 긍정+상승 → "긍정적인 뉴스 흐름 속에 주가도 상승했어요. 우호적인 하루였어요."
  - 긍정+하락 → "뉴스는 긍정적이지만 주가는 하락했어요. 차익실현 움직임일 수 있어요."
  - 부정+하락 / 부정+상승 / 중립 … (총 5분기) + RSI≥70 과열 / ≤30 과매도 경고 한 문장 덧붙임
- **신호 칩 5종** (가로 1줄): 감성🟢🔴⚪ · RSI · 거래량(±%) · 추세(MACD 강세/약세) · 1일(±%). 색: 긍정/강세=초록, 부정/약세=빨강, 과열=주황, 거래량활발=파랑, 중립=회색

### ② 거래일별 흐름 (멀티데이 · `/analysis/ticker-timeline`)
- 세로 타임라인. 세션마다: 점(감성색) + `M/D 장`(마지막은 `· 오늘자`) + 감성 + 대표 헤드라인(+N건)
- 점/선 색: positive=초록, negative=빨강, neutral=회색
- 헤더에 "· 미국장 마감 기준" 표기

### ③ 어제 → 오늘 흐름 (`sections`)
- 세로 3단 연결 타임라인:
  1. `어제 마감 이후 무슨 일이` ← `sections.어제의_핵심` (회색)
  2. `주가는 이렇게 반응` ← `sections.주가_반응` (파랑)
  3. `그래서 오늘 볼 것은` ← `sections.오늘_전망` (초록)
- `sections` 없으면 `summary`를 문장 단위 불릿으로 분해해 폴백

### ④ 오늘의 뉴스 (`news_articles`, 감성별 그룹)
- 🟢 호재·긍정 / 🔴 악재·주의 / ⚪ 주목 으로 묶음. 그룹별 최대 3건
- 카드: 좌측 감성색 보더 + 감성 pill(`긍정 +78`) + 날짜 + headline_ko + summary

### 색·스케일 토큰
- 초록 `#16a34a` / 빨강 `#ef4444` / 주황 `#ea580c` / 파랑 `#2563eb` / 회색 `#9aa5b4`
- **감성점수 표시 = raw×100** (raw -1~1 → -100~100, 부호 유지). `Math.round(score*100)`
  - 안전: `Math.abs(score)<=1 ? round(score*100) : round(score)` (이미 스케일된 값 들어와도 방어)

---

## 4. 통합 순서 (권장)

1. 타입 추가(§2) → `DigestCard`에서 `sections`/`news_articles` 사용
2. ①한마디 ③어제→오늘 ④뉴스 먼저 (기존 digest 응답만으로 가능, 신규 API 불필요)
3. ②거래일별 흐름은 `/analysis/ticker-timeline` 연동 후 추가 (티커별 fetch + 캐시 권장)

문의: BE/디자인 관련 막히면 `digest-summary-preview.html` 코드 그대로 참고하면 됩니다.
