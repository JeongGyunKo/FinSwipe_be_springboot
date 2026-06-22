from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from app.core import get_settings
from app.db.postgres import connect_postgres
from app.services.gemini.client import gemini_generate_content

logger = logging.getLogger(__name__)

_LEVEL_LABELS = {1: "입문", 2: "기초", 3: "중급", 4: "고급", 5: "전문가"}

_LEVEL_DEPTH = {
    1: "초등학생도 이해할 수 있을 정도로 매우 쉽게, 비유를 들어 설명해주세요. 전문 용어는 쓰지 마세요.",
    2: "주식을 시작한 지 얼마 안 된 초보 투자자에게 설명하듯 쉽게 설명하되 기본 용어는 사용해도 됩니다.",
    3: "PER, RSI, MACD 같은 중급 개념을 알고 있는 투자자 수준으로 설명해주세요.",
    4: "재무 분석과 기술적 분석을 이해하는 투자자에게 설명하듯 심화 내용을 포함해주세요.",
    5: "전문 투자자 수준으로 정량적 분석, 리스크 팩터, 알파 시그널 관점까지 포함해 설명해주세요.",
}

_TENDENCY_FOCUS = {
    "가치투자형 투자자": "기업 내재가치와 장기 펀더멘털 관점에서 분석하세요. PER·PBR·FCF 같은 재무지표를 중심으로 오늘 뉴스가 밸류에이션에 미치는 영향을 설명하세요.",
    "모멘텀형 투자자": "단기 가격 흐름과 시장 추세 관점에서 분석하세요. 오늘 뉴스가 RSI·MACD 기술적 시그널과 모멘텀에 어떤 영향을 주는지 중심으로 설명하세요.",
    "안정추구형 투자자": "리스크 요소와 하방 리스크를 중심으로 분석하세요. 오늘 뉴스가 포트폴리오 안정성에 미치는 영향을 손실 방어 관점에서 설명하세요.",
    "거시경제형 투자자": "금리·환율·경기 사이클 등 거시경제 관점에서 분석하세요. 오늘 뉴스가 매크로 환경과 어떻게 연결되는지 설명하세요.",
    "탐색형 투자자": "최대한 쉽고 친절하게 설명해주세요. 전문 용어는 괄호 안에 간단히 풀어서 설명하세요.",
}

_DEFAULT_TENDENCY_FOCUS = _TENDENCY_FOCUS["탐색형 투자자"]

_SYSTEM_PROMPT = """당신은 개인화 금융 뉴스 분석 전문가입니다.
종목의 뉴스와 기술적 지표를 분석해 투자자 맞춤 일일 브리핑을 제공합니다.

반드시 아래 JSON 형식으로만 답변하세요 (코드블록 없이, 순수 JSON만):
{
  "어제의_핵심": "어제 이 종목에서 일어난 핵심 이벤트와 뉴스 흐름 — 2~3문장",
  "주가_반응": "어제 뉴스에 주가가 어떻게 반응했는지, RSI·MACD 등 기술적 지표와 연결해 해석 — 2~3문장",
  "오늘_전망": "어제 흐름을 바탕으로 오늘 주목할 포인트, 이 투자자 성향에서 봐야 할 것 — 2~3문장"
}

규칙:
- 반드시 한국어로 답변
- 각 섹션은 2~3문장, 핵심만 간결하게
- 투자자의 레벨과 성향에 맞게 작성
- 기술적 지표(RSI·MACD·볼린저밴드·거래량 수치)를 실제 분석에 활용
- JSON 외 다른 텍스트 출력 금지"""


def _fetch_user_profile(user_id: str, settings) -> dict | None:
    with connect_postgres(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT tickers, level, tendency FROM user_profiles WHERE id = CAST(%s AS UUID)",
                (user_id,),
            )
            row = cur.fetchone()
    if row is None:
        return None
    return {
        "tickers": list(row["tickers"] or []),
        "level": int(row["level"] or 3),
        "tendency": str(row["tendency"] or "탐색형 투자자"),
    }


def _fetch_ticker_articles(ticker: str, settings) -> list[dict]:
    """어제 미국 장 마감(16:00 ET ≈ NOW()-24h) 이후 기사를 감성점수 절대값 내림차순으로 최대 10건."""
    with connect_postgres(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT headline_ko, headline, sentiment_label, sentiment_score,
                       sentiment_reason, published_at
                FROM news_articles
                WHERE %s = ANY(tickers)
                  AND published_at >= NOW() - INTERVAL '24 hours'
                  AND (headline_ko IS NOT NULL OR headline IS NOT NULL)
                ORDER BY ABS(sentiment_score) DESC, published_at DESC
                LIMIT 10
                """,
                (ticker,),
            )
            rows = cur.fetchall()
    return [dict(r) for r in rows]


def _sentiment_overview(articles: list[dict]) -> dict:
    pos = sum(1 for a in articles if (a.get("sentiment_label") or "") == "positive")
    neg = sum(1 for a in articles if (a.get("sentiment_label") or "") == "negative")
    scores = [float(a["sentiment_score"]) for a in articles if a.get("sentiment_score") is not None]
    return {
        "positive": pos,
        "negative": neg,
        "neutral": len(articles) - pos - neg,
        "avg_score": round(sum(scores) / len(scores), 3) if scores else 0.0,
    }


def _build_digest_prompt(
    ticker: str,
    articles: list[dict],
    level: int,
    tendency: str,
    technicals: dict | None = None,
) -> str:
    lines = []
    for i, a in enumerate(articles[:8], 1):
        title = (a.get("headline_ko") or a.get("headline") or "").strip()
        label = a.get("sentiment_label") or "neutral"
        score = float(a.get("sentiment_score") or 0.0)
        reason = (a.get("sentiment_reason") or "").strip()
        lines.append(f"{i}. [{label}|{score:+.2f}] {title}")
        if reason:
            lines.append(f"   → {reason[:120]}")

    depth = _LEVEL_DEPTH.get(level, _LEVEL_DEPTH[3])
    focus = _TENDENCY_FOCUS.get(tendency, _DEFAULT_TENDENCY_FOCUS)
    label_str = _LEVEL_LABELS.get(level, "중급")

    ti_block = ""
    if technicals:
        c1d = technicals.get("change_pct_1d")
        c1m = technicals.get("change_pct_1m")
        rsi = technicals.get("RSI")
        rsi_sig = technicals.get("RSI_signal", "")
        macd = technicals.get("MACD") or {}
        macd_trend = macd.get("trend", "")
        macd_hist = macd.get("histogram")
        vr = technicals.get("volume_ratio")
        bb = technicals.get("BB") or {}
        bb_pos = bb.get("position", "")
        bb_pct = bb.get("pct_b")
        w52 = technicals.get("week52") or {}
        w52_pct = w52.get("position_pct")
        ma20 = technicals.get("MA20_diff_pct")

        parts = []
        if c1d is not None:
            parts.append(f"1일 변동 {c1d:+.2f}%")
        if c1m is not None:
            parts.append(f"1개월 {c1m:+.2f}%")
        if rsi is not None:
            parts.append(f"RSI {rsi:.1f}({rsi_sig})")
        if macd_trend and macd_hist is not None:
            parts.append(f"MACD {macd_trend}(hist {macd_hist:+.4f})")
        if bb_pos and bb_pct is not None:
            parts.append(f"볼린저밴드 {bb_pos}({bb_pct:.0f}%)")
        if vr is not None:
            parts.append(f"거래량 평균대비 {vr:.2f}x")
        if w52_pct is not None:
            parts.append(f"52주 위치 {w52_pct:.0f}%")
        if ma20 is not None:
            parts.append(f"MA20 대비 {ma20:+.2f}%")

        if parts:
            ti_block = "\n[기술적 지표] " + " / ".join(parts)

    return (
        f"[종목] {ticker}\n"
        f"[사용자 프로필] 레벨: {level}/5 ({label_str}) / 성향: {tendency}\n\n"
        f"[어제 뉴스 {len(articles)}건]\n"
        + "\n".join(lines)
        + ti_block
        + f"\n\n[분석 깊이] {depth}\n"
        f"[성향 초점] {focus}\n\n"
        f"위 정보를 바탕으로 {ticker} 일일 브리핑 JSON을 작성하세요."
    )


def _fetch_technicals(ticker: str) -> dict | None:
    try:
        import numpy as np
        import yfinance as yf

        # 52주 위치 계산을 위해 1y 데이터 사용 — 신규 상장 종목은 데이터가 적어도 현재가/등락률 반환
        hist = yf.Ticker(ticker).history(period="1y", interval="1d")
        if hist.empty or len(hist) < 2:
            return None

        prices = hist["Close"].values.astype(float)
        opens = hist["Open"].values.astype(float)
        volumes = hist["Volume"].values.astype(float)

        open_price = round(float(opens[-1]), 2) if len(opens) >= 1 else None
        change_open_to_close = round((prices[-1] / opens[-1] - 1) * 100, 2) if len(opens) >= 1 and opens[-1] > 0 else None
        change_1d = round((prices[-1] / prices[-2] - 1) * 100, 2) if len(prices) >= 2 else None
        change_1m = round((prices[-1] / prices[-22] - 1) * 100, 2) if len(prices) >= 22 else None

        # 당일 누적 거래량 (뉴스 분석 시점 기준 실시간)
        try:
            intraday = yf.Ticker(ticker).history(period="1d", interval="1m")
            current_volume = int(intraday["Volume"].sum()) if not intraday.empty else None
            # 1분봉 마지막 종가 — 일봉 종가보다 최신 (약 15분 지연)
            if not intraday.empty:
                current_price = round(float(intraday["Close"].values[-1]), 2)
            else:
                current_price = round(float(prices[-1]), 2)
        except Exception:
            current_volume = None
            current_price = round(float(prices[-1]), 2)
        avg_daily_volume = float(volumes[-5:].mean()) if len(volumes) >= 5 else None
        volume_ratio = round(current_volume / avg_daily_volume, 2) if current_volume and avg_daily_volume else (
            round(float(volumes[-1] / avg_daily_volume), 2) if avg_daily_volume else None
        )

        # RSI (14일) — 데이터 부족 시 None
        rsi = None
        rsi_signal = None
        if len(prices) >= 15:
            deltas = np.diff(prices[-29:])
            gains = np.where(deltas > 0, deltas, 0.0)
            losses = np.where(deltas < 0, -deltas, 0.0)
            avg_gain = gains[-14:].mean()
            avg_loss = losses[-14:].mean()
            rsi = round(100 - 100 / (1 + avg_gain / avg_loss), 1) if avg_loss != 0 else 100.0
            rsi_signal = "과매수" if rsi > 70 else "과매도" if rsi < 30 else "중립"

        # MACD (12/26/9) — 데이터 부족 시 None
        macd_data = None
        if len(prices) >= 26:
            def ema(arr: "np.ndarray", span: int) -> "np.ndarray":
                k = 2 / (span + 1)
                r = np.zeros(len(arr))
                r[0] = arr[0]
                for i in range(1, len(arr)):
                    r[i] = arr[i] * k + r[i - 1] * (1 - k)
                return r

            ema12 = ema(prices, 12)
            ema26 = ema(prices, 26)
            macd_line = ema12 - ema26
            signal_line = ema(macd_line, 9)
            histogram = round(float(macd_line[-1] - signal_line[-1]), 4)
            macd_data = {
                "macd": round(float(macd_line[-1]), 4),
                "signal": round(float(signal_line[-1]), 4),
                "histogram": histogram,
                "trend": "상승" if histogram > 0 else "하락",
            }

        # 볼린저밴드 (20일) — 데이터 부족 시 None
        bb_data = None
        ma20_diff_pct = None
        if len(prices) >= 20:
            ma20 = float(prices[-20:].mean())
            std20 = float(prices[-20:].std())
            bb_upper = ma20 + 2 * std20
            bb_lower = ma20 - 2 * std20
            bb_width = bb_upper - bb_lower
            bb_pct_b = round((prices[-1] - bb_lower) / bb_width * 100, 1) if bb_width > 0 else 50.0
            if prices[-1] > bb_upper:
                bb_position = "상단돌파"
            elif prices[-1] < bb_lower:
                bb_position = "하단돌파"
            elif bb_pct_b >= 60:
                bb_position = "상단"
            elif bb_pct_b <= 40:
                bb_position = "하단"
            else:
                bb_position = "중립"
            bb_data = {"upper": round(bb_upper, 2), "lower": round(bb_lower, 2), "pct_b": bb_pct_b, "position": bb_position}
            ma20_diff_pct = round((prices[-1] / ma20 - 1) * 100, 2)

        # 52주 고저 위치
        high_52w = float(prices.max())
        low_52w = float(prices.min())
        week52_range = high_52w - low_52w
        week52_position_pct = round((prices[-1] - low_52w) / week52_range * 100, 1) if week52_range > 0 else 50.0

        sparkline = [round(float(p), 2) for p in prices[-30:].tolist()]

        return {
            "current_price": current_price,
            "open_price": open_price,
            "change_open_to_close": change_open_to_close,
            "change_pct_1d": change_1d,
            "change_pct_1m": change_1m,
            "volume_ratio": volume_ratio,
            "RSI": rsi,
            "RSI_signal": rsi_signal,
            "MACD": macd_data,
            "BB": bb_data,
            "MA20_diff_pct": ma20_diff_pct,
            "week52": {
                "high": round(high_52w, 2),
                "low": round(low_52w, 2),
                "position_pct": week52_position_pct,
            },
            "sparkline": sparkline,
        }
    except Exception as exc:
        logger.warning("[다이제스트] %s 기술적 지표 수집 실패: %s", ticker, exc)
        return None


_UNSET = object()


def _generate_single_ticker_digest(
    ticker: str,
    level: int,
    tendency: str,
    settings,
    technicals=_UNSET,
) -> dict:
    """티커 1개에 대한 다이제스트를 생성한다.

    technicals를 외부에서 주입하면 yfinance 호출을 생략한다
    (digest_worker에서 티커당 1번만 호출하기 위해 사용).
    """
    articles = _fetch_ticker_articles(ticker, settings)
    resolved_technicals = _fetch_technicals(ticker) if technicals is _UNSET else technicals

    def _serialize_article(a: dict) -> dict:
        pub = a.get("published_at")
        return {
            "headline_ko": a.get("headline_ko"),
            "headline": a.get("headline"),
            "sentiment_label": a.get("sentiment_label"),
            "sentiment_score": float(a.get("sentiment_score") or 0),
            "published_at": pub.isoformat() if pub else None,
        }

    if not articles:
        return {
            "ticker": ticker,
            "articles_count": 0,
            "message": "오늘 관련 뉴스가 없습니다.",
            "sentiment_overview": None,
            "summary": None,
            "sections": None,
            "news_articles": [],
            "technical_indicators": resolved_technicals,
        }

    overview = _sentiment_overview(articles)

    sections = None
    summary = None
    try:
        prompt = _build_digest_prompt(ticker, articles, level, tendency, resolved_technicals)
        raw = gemini_generate_content(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=prompt,
            model=settings.gemini_summary_model,
            temperature=0.3,
            request_label="daily_digest",
        ).strip()

        # ```json ... ``` 코드블록 제거
        clean = raw
        if clean.startswith("```"):
            parts = clean.split("```")
            clean = parts[1] if len(parts) > 1 else clean
            if clean.startswith("json"):
                clean = clean[4:]
        clean = clean.strip()

        try:
            parsed = json.loads(clean)
            sections = {
                "어제의_핵심": parsed.get("어제의_핵심", ""),
                "주가_반응": parsed.get("주가_반응", ""),
                "오늘_전망": parsed.get("오늘_전망", ""),
            }
            summary = " ".join(filter(None, sections.values()))
        except json.JSONDecodeError:
            logger.warning("[다이제스트] %s JSON 파싱 실패, 원문 사용", ticker)
            summary = raw

    except Exception as exc:
        logger.error("[다이제스트] %s 요약 생성 실패: %s", ticker, exc)

    return {
        "ticker": ticker,
        "articles_count": len(articles),
        "sentiment_overview": overview,
        "summary": summary,
        "sections": sections,
        "news_articles": [_serialize_article(a) for a in articles if a.get("headline_ko")][:5],
        "technical_indicators": resolved_technicals,
    }


def get_cached_ticker_digest(ticker: str, level: int, tendency: str, settings) -> dict | None:
    """digest_cache에서 (ticker, level, tendency) 캐시를 조회한다."""
    with connect_postgres(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT digest_json, generated_at FROM digest_cache
                WHERE ticker = %s AND level = %s AND tendency = %s
                """,
                (ticker, level, tendency),
            )
            row = cur.fetchone()
    if row is None:
        return None
    result = dict(row["digest_json"])
    result["cached_at"] = row["generated_at"].isoformat()
    return result


def save_ticker_digest_cache(ticker: str, level: int, tendency: str, digest: dict, settings) -> None:
    """(ticker, level, tendency) 다이제스트 결과를 digest_cache에 저장/갱신한다."""
    payload = {k: v for k, v in digest.items() if k != "cached_at"}
    with connect_postgres(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO digest_cache (ticker, level, tendency, digest_json, generated_at)
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (ticker, level, tendency)
                DO UPDATE SET digest_json = EXCLUDED.digest_json,
                              generated_at = EXCLUDED.generated_at
                """,
                (ticker, level, tendency, json.dumps(payload, default=str)),
            )
        conn.commit()


def generate_digest_from_cache(user_id: str) -> dict:
    """캐시 우선 조회 후 캐시 미스 시 온디맨드 생성으로 폴백하는 다이제스트 반환."""
    settings = get_settings()

    profile = _fetch_user_profile(user_id, settings)
    if profile is None:
        return {"error": "사용자를 찾을 수 없습니다.", "digests": []}

    tickers: list[str] = profile["tickers"]
    level: int = profile["level"]
    tendency: str = profile["tendency"]

    if not tickers:
        return {
            "digests": [],
            "user_level": level,
            "user_tendency": tendency,
            "message": "관심 티커가 없습니다. 티커를 먼저 추가하세요.",
        }

    digests = []
    for ticker in tickers[:10]:
        cached = get_cached_ticker_digest(ticker, level, tendency, settings)
        if cached is not None:
            digests.append(cached)
        else:
            result = _generate_single_ticker_digest(ticker, level, tendency, settings)
            try:
                save_ticker_digest_cache(ticker, level, tendency, result, settings)
            except Exception as exc:
                logger.warning("[다이제스트] %s 캐시 저장 실패: %s", ticker, exc)
            digests.append(result)

    return {
        "digests": digests,
        "user_level": level,
        "user_tendency": tendency,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def generate_digest(user_id: str) -> dict:
    settings = get_settings()

    profile = _fetch_user_profile(user_id, settings)
    if profile is None:
        return {"error": "사용자를 찾을 수 없습니다.", "digests": []}

    tickers: list[str] = profile["tickers"]
    level: int = profile["level"]
    tendency: str = profile["tendency"]

    if not tickers:
        return {
            "digests": [],
            "user_level": level,
            "user_tendency": tendency,
            "message": "관심 티커가 없습니다. 티커를 먼저 추가하세요.",
        }

    digests = [
        _generate_single_ticker_digest(ticker, level, tendency, settings)
        for ticker in tickers[:10]
    ]

    return {
        "digests": digests,
        "user_level": level,
        "user_tendency": tendency,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
