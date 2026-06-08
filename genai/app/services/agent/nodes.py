from __future__ import annotations

import logging

import numpy as np

from app.services.agent.state import AnalysisState

logger = logging.getLogger(__name__)

_LEVEL_LABELS = {1: "입문", 2: "기초", 3: "중급", 4: "고급", 5: "전문가"}

_TENDENCY_FOCUS = {
    "가치투자형":  "기업 내재가치와 장기 펀더멘털 관점에서 분석해주세요. PER/PBR 같은 재무지표를 중심으로 설명하세요.",
    "모멘텀형":    "단기 가격 흐름과 시장 추세 관점에서 분석해주세요. 기술적 지표(RSI, MACD)의 시그널을 중심으로 설명하세요.",
    "안정추구형":  "리스크 요소와 하방 리스크를 중심으로 분석해주세요. 손실 방어 관점에서 설명하세요.",
    "공격성장형":  "성장 가능성과 상방 잠재력을 중심으로 분석해주세요. 모멘텀과 성장 시그널에 집중하세요.",
    "인컴형":      "배당 안정성과 현금흐름 관점에서 분석해주세요. 정기 수익에 미치는 영향을 중심으로 설명하세요.",
    "탐색형":      "최대한 쉽고 친절하게 설명해주세요. 전문 용어는 괄호 안에 간단히 풀어서 설명하세요.",
}

_LEVEL_DEPTH = {
    1: "초등학생도 이해할 수 있을 정도로 매우 쉽게, 비유를 들어 설명해주세요. 전문 용어는 쓰지 마세요.",
    2: "주식을 시작한 지 얼마 안 된 초보 투자자에게 설명하듯 쉽게 설명하되 기본 용어는 사용해도 됩니다.",
    3: "PER, RSI, MACD 같은 중급 개념을 알고 있는 투자자 수준으로 설명해주세요.",
    4: "재무 분석과 기술적 분석을 이해하는 투자자에게 설명하듯 심화 내용을 포함해주세요.",
    5: "전문 투자자 수준으로 정량적 분석, 리스크 팩터, 알파 시그널 관점까지 포함해 설명해주세요.",
}


# ── Node 1: 주가 데이터 수집 ──────────────────────────────────────────────────

def fetch_price_data(state: AnalysisState) -> dict:
    tickers = state.get("tickers") or []
    if not tickers:
        logger.info("[에이전트] 티커 없음 → 주가 수집 스킵")
        return {"price_data": None}

    import yfinance as yf

    price_data = {}
    for ticker in tickers[:3]:  # 최대 3개 티커만 처리
        try:
            hist = yf.Ticker(ticker).history(period="3mo", interval="1d")
            if hist.empty:
                continue
            price_data[ticker] = hist["Close"].tolist()
            logger.info("[에이전트] 주가 수집: %s (%d일)", ticker, len(price_data[ticker]))
        except Exception as exc:
            logger.warning("[에이전트] 주가 수집 실패: %s — %s", ticker, exc)

    return {"price_data": price_data if price_data else None}


# ── Node 2: 기술적 지표 계산 ────────────────────────────────────────────────

def calculate_technicals(state: AnalysisState) -> dict:
    price_data = state.get("price_data")
    if not price_data:
        return {"technical_indicators": None}

    indicators = {}
    for ticker, closes in price_data.items():
        if len(closes) < 26:
            continue
        prices = np.array(closes, dtype=float)
        indicators[ticker] = {
            "RSI": _rsi(prices),
            "MACD": _macd(prices),
            "current_price": round(float(prices[-1]), 2),
            "change_pct_1m": round((prices[-1] / prices[-22] - 1) * 100, 2) if len(prices) >= 22 else None,
        }
        logger.info("[에이전트] 지표 계산: %s RSI=%.1f", ticker, indicators[ticker]["RSI"])

    return {"technical_indicators": indicators if indicators else None}


def _rsi(prices: np.ndarray, period: int = 14) -> float:
    deltas = np.diff(prices[-period * 2:])
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = gains[-period:].mean()
    avg_loss = losses[-period:].mean()
    if avg_loss == 0:
        return 100.0
    return round(100 - 100 / (1 + avg_gain / avg_loss), 1)


def _macd(prices: np.ndarray) -> dict:
    def ema(arr: np.ndarray, span: int) -> np.ndarray:
        k = 2 / (span + 1)
        result = np.zeros(len(arr))
        result[0] = arr[0]
        for i in range(1, len(arr)):
            result[i] = arr[i] * k + result[i - 1] * (1 - k)
        return result

    ema12 = ema(prices, 12)
    ema26 = ema(prices, 26)
    macd_line = ema12 - ema26
    signal_line = ema(macd_line, 9)
    histogram = macd_line[-1] - signal_line[-1]
    return {
        "macd": round(float(macd_line[-1]), 4),
        "signal": round(float(signal_line[-1]), 4),
        "histogram": round(float(histogram), 4),
        "trend": "상승" if histogram > 0 else "하락",
    }


# ── Node 3: 맞춤 분석 생성 ──────────────────────────────────────────────────

def generate_personalized_analysis(state: AnalysisState) -> dict:
    from app.services.gemini.client import gemini_generate_content
    from app.core import get_settings

    settings = get_settings()
    level = state["user_level"]
    tendency = state["user_tendency"]
    indicators = state.get("technical_indicators")

    # 기술적 지표 텍스트 구성
    indicator_text = ""
    if indicators:
        for ticker, ind in indicators.items():
            rsi = ind["RSI"]
            macd = ind["MACD"]
            rsi_signal = "과매수 구간" if rsi > 70 else "과매도 구간" if rsi < 30 else "중립"
            indicator_text += f"""
[{ticker} 기술적 지표]
- 현재가: ${ind['current_price']}
- 1개월 수익률: {ind.get('change_pct_1m', 'N/A')}%
- RSI({rsi}): {rsi_signal}
- MACD: {macd['macd']:.4f} | Signal: {macd['signal']:.4f} | 추세: {macd['trend']}
"""

    system_prompt = """당신은 사용자 맞춤형 금융 분석 전문가입니다.
주어진 뉴스 감성 분석 결과와 기술적 지표를 바탕으로,
사용자의 지식 레벨과 투자 성향에 맞게 분석을 제공합니다.
반드시 한국어로 답변하세요."""

    user_prompt = f"""
[뉴스 정보]
제목: {state['article_title']}
감성: {state['sentiment_label']} (점수: {state['sentiment_score']:.1f})
감성 이유: {state['sentiment_reason']}
{indicator_text}

[사용자 프로필]
지식 레벨: {level}/5 ({_LEVEL_LABELS[level]})
투자 성향: {tendency}

[분석 지침]
깊이: {_LEVEL_DEPTH[level]}
성향 초점: {_TENDENCY_FOCUS.get(tendency, '')}

위 정보를 바탕으로 이 투자자에게 맞는 분석을 3~5문장으로 작성해주세요.
"""

    try:
        result = gemini_generate_content(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=settings.gemini_summary_model,
            temperature=0.3,
            request_label="personalized_analysis",
        )
        return {"personalized_analysis": result.strip()}
    except Exception as exc:
        logger.error("[에이전트] 맞춤 분석 생성 실패: %s", exc, exc_info=True)
        return {"personalized_analysis": None, "error": "분석 처리 중 오류가 발생했습니다."}
