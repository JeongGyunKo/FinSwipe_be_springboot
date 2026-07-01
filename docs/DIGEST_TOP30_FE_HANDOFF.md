# "오늘의 top30 통합 브리핑" — FE 핸드오프

카드 피드를 **다 읽었을 때** 보여주는 요약 화면이 바뀌었습니다.

- **이전**: 관심 종목별로 각각 카드(어제의_핵심/주가_반응/오늘_전망 + 지표) — `digests[]` 배열
- **이후**: 관심종목 무관, **오늘 노출된 top30(절대값 파워 상위 30) 뉴스를 한 편으로 종합한 통합 브리핑 1개 + 대표 종목 보조지표**

## 엔드포인트 (변경 없음)

```
POST /analysis/digest
Authorization: Bearer <JWT>
```
- 요청 바디 없음(로그인 유저 기준). 엔드포인트 경로·메서드 그대로.
- **응답 구조가 완전히 바뀌었습니다.** 아래 참고.

## 응답 구조 (신규)

```json
{
  "type": "feed_top30",
  "articles_count": 30,
  "sentiment_overview": { "positive": 14, "negative": 11, "neutral": 5, "avg_score": 0.12 },
  "briefing": {
    "오늘의_시장": "오늘은 반도체 강세와 금리 경계가 동시에 나타나며 혼조세를 보였어요.",
    "핵심_이슈": "엔비디아 실적 서프라이즈가 반도체 전반을 끌어올렸고, 연준 발언이 상승폭을 제한했습니다.",
    "오늘_체크포인트": "모멘텀 관점에서 반도체 대형주 거래량과 국채금리 흐름을 함께 보세요."
  },
  "summary": "오늘은 ... / 엔비디아 ... / 모멘텀 관점 ...",
  "top_articles": [
    { "headline_ko": "엔비디아 실적 서프라이즈", "headline": "Nvidia beats estimates",
      "sentiment_label": "positive", "sentiment_score": 0.91, "tickers": ["NVDA"],
      "published_at": "2026-07-01T20:15:00Z" }
  ],
  "indicators": [
    { "ticker": "NVDA", "current_price": 128.4, "change_pct_1d": 3.2, "change_pct_1m": 11.5,
      "volume_ratio": 1.8, "RSI": 68.0, "RSI_signal": "중립",
      "MACD": { "macd": 0.42, "signal": 0.31, "histogram": 0.11, "trend": "상승" },
      "BB": { "position": "상단", "pct_b": 72.0 }, "week52": { "position_pct": 88.0 },
      "sparkline": [/* 최근 30일 종가 */] }
  ],
  "user_level": 3,
  "user_tendency": "모멘텀형 투자자",
  "generated_at": "2026-07-01T15:30:00Z"
}
```

### 필드 설명
- `briefing`: **핵심.** 하루 시장을 종합한 3단 브리핑. 이걸 메인으로 렌더하세요.
  - 생성 실패 시 `briefing`이 `null` → 이때 `summary`(한 덩어리 텍스트) 폴백 사용.
- `summary`: 3단을 이어붙인 텍스트(폴백용).
- `sentiment_overview`: 30건의 긍/부정/중립 카운트 + 평균 점수 → 상단 요약 뱃지/도넛 등에 활용.
- `top_articles`: 대표 기사 최대 10건(파워순). 카드 리스트로.
- `indicators`: top30에 많이 등장한 **대표 종목 최대 8개**의 보조지표(RSI·MACD·볼린저·거래량·52주위치·sparkline). 종목별 지표 위젯으로.
- `user_level` / `user_tendency`: 개인화 표시용(선택).

### 빈 상태
오늘 노출된 뉴스가 없으면:
```json
{ "type": "feed_top30", "articles_count": 0, "message": "오늘 노출된 뉴스가 없습니다.",
  "briefing": null, "summary": null, "sentiment_overview": null, "top_articles": [], "indicators": [] }
```
→ "오늘의 브리핑 준비 중" 같은 빈 상태로 처리.

## 성능 참고
- (레벨,성향)별로 서버 캐시됩니다. 백그라운드 worker가 새 기사 감지 시 미리 만들어두므로 보통 즉시 응답.
- 캐시가 없는 순간(그날 첫 요청 등)엔 즉석 생성으로 **수~십수 초** 걸릴 수 있어요. 로딩 스피너 처리 권장.

## FE가 바꿔야 할 것 요약
1. `digests[]` 순회 렌더링 코드 제거 → `briefing` 3단 + `indicators`/`top_articles` 렌더로 교체.
2. 엔드포인트 호출 코드는 그대로.
3. `briefing == null`이면 `summary` 폴백, `articles_count == 0`이면 빈 상태.
