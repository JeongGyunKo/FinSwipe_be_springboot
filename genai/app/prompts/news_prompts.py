"""뉴스 분석 프롬프트 — Gemini는 요약 + 한국어 번역만 담당
감성 분석: FinBERT (로컬)
XAI:       LIME (로컬)
요약/번역:  Gemini
"""

# ── 요약 + 한국어 번역 ────────────────────────────────────────────────────────

SUMMARIZE_SYSTEM = """당신은 금융 뉴스 번역·요약 전문가입니다.

주어진 금융 뉴스 기사를 분석하여 다음을 수행합니다:
1. **영어 3줄 요약**: 핵심 내용을 영어로 3줄 요약
2. **한국어 제목**: 원문 제목을 자연스러운 한국어로 번역
3. **한국어 3줄 요약**: 영어 요약을 한국어로 번역

## 출력 형식 (JSON만 출력, 다른 텍스트 없음)
```json
{
  "summary_3lines": [
    "First key point in English",
    "Second key point in English",
    "Third key point in English"
  ],
  "localized": {
    "title": "한국어 제목",
    "summary_3lines": [
      "첫 번째 핵심 내용 (한국어)",
      "두 번째 핵심 내용 (한국어)",
      "세 번째 핵심 내용 (한국어)"
    ]
  }
}
```

기사 내용이 너무 짧거나 금융과 무관한 경우 summary_3lines를 빈 배열로 반환하세요."""


def build_summarize_messages(title: str, article_text: str,
                             summary_text: str | None = None,
                             tickers: list[str] | None = None) -> list[dict]:
    """요약/번역 요청 메시지 생성"""
    parts = []
    if tickers:
        parts.append(f"관련 티커: {', '.join(tickers)}")
    parts.append(f"제목: {title}")
    if summary_text:
        parts.append(f"요약: {summary_text}")
    parts.append(f"\n본문:\n{article_text[:6000]}")
    return [{"role": "user", "content": "\n".join(parts)}]


# ── 티커별 뉴스 요약 (레벨 맞춤) ────────────────────────────────────────────

LEVEL_DESCRIPTIONS = {
    1: "입문자 (주식이 뭔지 이제 막 배우기 시작한 수준, 쉬운 일상 언어 사용)",
    2: "초보자 (기본 주식 용어를 아는 수준, 전문 용어 최소화)",
    3: "중급자 (PER, PBR, 시가총액 등 기본 지표를 아는 수준)",
    4: "고급자 (재무제표, DCF, 섹터 분석 등을 이해하는 수준)",
    5: "전문가 (매크로경제, 알고리즘 트레이딩, 파생상품 등 고급 전략 이해)",
}

TICKER_SUMMARY_SYSTEM = """당신은 금융 뉴스 큐레이터 AI입니다.
특정 종목의 최근 뉴스들을 분석하여 사용자 수준에 맞는 종합 요약을 한국어로 제공합니다.

## 출력 형식 (JSON만 출력)
```json
{
  "summary": "전체 종합 요약 (2-3문장, 한국어)",
  "key_points": [
    "핵심 포인트 1 (한국어)",
    "핵심 포인트 2 (한국어)",
    "핵심 포인트 3 (한국어)"
  ],
  "sentiment_overview": "positive|negative|mixed|neutral"
}
```"""


def build_ticker_summary_messages(ticker: str, level: int,
                                  articles: list[dict]) -> list[dict]:
    """티커별 뉴스 요약 메시지"""
    level_desc = LEVEL_DESCRIPTIONS.get(level, LEVEL_DESCRIPTIONS[3])
    news_text = "\n\n".join(
        f"[{i+1}] {a.get('headline', '')} (감성: {a.get('sentiment_label', 'unknown')})\n"
        f"{'; '.join(a.get('summary_3lines_ko') or a.get('summary_3lines') or [])}"
        for i, a in enumerate(articles[:10])
    )
    content = (
        f"종목: {ticker}\n"
        f"사용자 수준: {level}단계 — {level_desc}\n\n"
        f"오늘의 관련 뉴스 {len(articles)}건:\n\n{news_text}\n\n"
        f"위 뉴스들을 {level}단계 사용자에게 맞는 언어로 종합 요약해주세요."
    )
    return [{"role": "user", "content": content}]
