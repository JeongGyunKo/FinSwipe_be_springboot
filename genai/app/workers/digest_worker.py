from __future__ import annotations

import argparse
import logging
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.core import get_settings
from app.core.logging import configure_logging, get_logger, log_event
from app.db.postgres import connect_postgres
from app.services.digest.agent import (
    _fetch_technicals,
    _generate_single_ticker_digest,
    save_ticker_digest_cache,
)

logger = get_logger(__name__)

_DEFAULT_POLL_INTERVAL = 60.0   # 초
_DEFAULT_MAX_WORKERS = 3        # Gemini 세마포어(5) 내에서 병렬 처리


def _fetch_stale_combos(settings) -> list[dict]:
    """어제 장마감 이후 새 기사가 있지만 캐시가 없거나 오래된 (ticker, level, tendency) 조합을 반환한다.

    조건:
    - user_profiles에 존재하는 실제 (level, tendency) 조합만 대상으로 한다.
    - news_articles에 최근 24시간 이내 기사가 있는 ticker만 대상으로 한다.
    - digest_cache가 없거나, 캐시 생성 이후 새 기사가 존재하는 경우에만 반환한다.
    """
    with connect_postgres(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT
                    t.ticker,
                    up.level::int   AS level,
                    up.tendency
                FROM user_profiles up
                CROSS JOIN LATERAL unnest(up.tickers) AS t(ticker)
                WHERE up.level    IS NOT NULL
                  AND up.tendency IS NOT NULL
                  AND array_length(up.tickers, 1) > 0
                  AND EXISTS (
                      SELECT 1 FROM news_articles na
                      WHERE t.ticker = ANY(na.tickers)
                        AND na.published_at >= NOW() - INTERVAL '24 hours'
                  )
                  AND (
                      NOT EXISTS (
                          SELECT 1 FROM digest_cache dc
                          WHERE dc.ticker   = t.ticker
                            AND dc.level    = up.level::int
                            AND dc.tendency = up.tendency
                      )
                      OR (
                          SELECT MAX(na2.published_at)
                          FROM news_articles na2
                          WHERE t.ticker = ANY(na2.tickers)
                            AND na2.published_at >= NOW() - INTERVAL '24 hours'
                      ) > (
                          SELECT dc2.generated_at
                          FROM digest_cache dc2
                          WHERE dc2.ticker   = t.ticker
                            AND dc2.level    = up.level::int
                            AND dc2.tendency = up.tendency
                      )
                  )
                LIMIT 30
                """
            )
            return [dict(row) for row in cur.fetchall()]


def _process_combo(combo: dict, technicals, settings) -> None:
    """(ticker, level, tendency) 조합 1개를 생성하고 캐시에 저장한다."""
    ticker = combo["ticker"]
    level = int(combo["level"])
    tendency = combo["tendency"]

    result = _generate_single_ticker_digest(ticker, level, tendency, settings, technicals=technicals)
    save_ticker_digest_cache(ticker, level, tendency, result, settings)


def _run_one_cycle(settings, max_workers: int) -> int:
    """스테일 조합을 조회하고 병렬로 재생성한다. 처리된 조합 수를 반환한다."""
    combos = _fetch_stale_combos(settings)
    if not combos:
        return 0

    # 티커별로 그룹핑 후 yfinance를 티커당 1번만 호출
    ticker_set: set[str] = {c["ticker"] for c in combos}
    ticker_technicals = {ticker: _fetch_technicals(ticker) for ticker in ticker_set}

    log_event(logger, logging.INFO, "digest_worker_regen_start",
              combo_count=len(combos), ticker_count=len(ticker_set))

    processed = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(
                _process_combo,
                combo,
                ticker_technicals[combo["ticker"]],
                settings,
            ): combo
            for combo in combos
        }
        for future in as_completed(futures):
            combo = futures[future]
            try:
                future.result()
                processed += 1
                log_event(
                    logger, logging.INFO, "digest_worker_combo_done",
                    ticker=combo["ticker"],
                    level=combo["level"],
                    tendency=combo["tendency"],
                )
            except Exception as exc:
                log_event(
                    logger, logging.ERROR, "digest_worker_combo_failed",
                    ticker=combo["ticker"],
                    level=combo["level"],
                    tendency=combo["tendency"],
                    error=str(exc),
                )

    log_event(
        logger, logging.INFO, "digest_worker_regen_done",
        processed=processed,
        total=len(combos),
    )
    return processed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Digest cache refresh worker")
    parser.add_argument("--once", action="store_true", help="한 사이클만 실행 후 종료")
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=_DEFAULT_POLL_INTERVAL,
        help="폴링 간격(초)",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=_DEFAULT_MAX_WORKERS,
        help="병렬 처리 스레드 수",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    configure_logging()
    settings = get_settings()

    log_event(
        logger, logging.INFO, "digest_worker_started",
        poll_interval_seconds=args.poll_interval,
        max_workers=args.max_workers,
    )

    if args.once:
        processed = _run_one_cycle(settings, args.max_workers)
        log_event(logger, logging.INFO, "digest_worker_run_once", processed=processed)
        return

    while True:
        try:
            _run_one_cycle(settings, args.max_workers)
        except Exception as exc:
            log_event(logger, logging.ERROR, "digest_worker_cycle_failed", error=str(exc))
        time.sleep(args.poll_interval)


if __name__ == "__main__":
    main()
