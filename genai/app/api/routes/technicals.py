from __future__ import annotations

import asyncio
import logging
import time
from threading import Lock

from fastapi import APIRouter, HTTPException

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/technicals", tags=["technicals"])

_cache: dict[str, tuple[float, dict]] = {}
_cache_lock = Lock()
_TTL = 900  # 15분


def _get_cached(ticker: str) -> dict | None:
    with _cache_lock:
        entry = _cache.get(ticker)
        if entry and (time.monotonic() - entry[0]) < _TTL:
            return entry[1]
        return None


def _set_cache(ticker: str, data: dict) -> None:
    with _cache_lock:
        _cache[ticker] = (time.monotonic(), data)


@router.get("/{ticker}")
async def get_technicals(ticker: str) -> dict:
    """티커별 기술적 지표 단건 조회 (30~60분 캐시)."""
    ticker = ticker.strip().upper()

    cached = _get_cached(ticker)
    if cached is not None:
        return cached

    try:
        from app.services.digest.agent import _fetch_technicals
        data = await asyncio.to_thread(_fetch_technicals, ticker)
    except Exception as exc:
        logger.error("[기술적지표] %s 조회 실패: %s", ticker, exc, exc_info=True)
        raise HTTPException(status_code=502, detail="기술적 지표 조회 중 오류가 발생했습니다.") from exc

    if data is None:
        raise HTTPException(status_code=404, detail=f"{ticker} 기술적 지표를 계산할 수 없습니다.")

    result = {"ticker": ticker, **data}
    _set_cache(ticker, result)
    return result
