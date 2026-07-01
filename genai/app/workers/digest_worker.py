from __future__ import annotations

import argparse
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.core import get_settings
from app.core.logging import configure_logging, get_logger, log_event
from app.db.postgres import connect_postgres
from app.services.digest.agent import (
    _FEED_SENTINEL,
    _build_feed_digest,
    _compute_top_tickers_indicators,
    _fetch_top30_articles,
    _get_feed_cache,
    save_ticker_digest_cache,
)

logger = get_logger(__name__)

_DEFAULT_POLL_INTERVAL = 60.0   # 초
_DEFAULT_MAX_WORKERS = 3        # Gemini 세마포어(5) 내에서 병렬 처리

# 프로필이 없거나 레벨/성향이 비어있는 유저의 온디맨드 기본값 — 항상 프리워밍 대상에 포함
_DEFAULT_COMBO = (3, "탐색형 투자자")


def _fetch_distinct_combos(settings) -> list[tuple[int, str]]:
    """user_profiles에 존재하는 (level, tendency) 조합 + 기본 조합을 반환한다.

    피드 브리핑은 관심종목과 무관하게 '오늘 top30' 전체를 요약하므로,
    캐시 키는 티커가 아니라 (레벨, 성향)뿐이다.
    """
    with connect_postgres(settings.postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT up.level::int AS level, up.tendency
                FROM user_profiles up
                WHERE up.level IS NOT NULL AND up.tendency IS NOT NULL
                """
            )
            combos = {(int(r["level"]), r["tendency"]) for r in cur.fetchall()}
    combos.add(_DEFAULT_COMBO)
    return sorted(combos)


def _run_one_cycle(settings, max_workers: int) -> int:
    """오늘 top30을 한 번 조회하고, 스테일한 (레벨,성향) 브리핑을 병렬 재생성한다."""
    articles = _fetch_top30_articles(settings)
    if not articles:
        return 0

    newest = max((a["published_at"] for a in articles if a.get("published_at")), default=None)

    # 캐시가 없거나 top30 최신 기사보다 오래된 조합만 재생성 대상
    stale: list[tuple[int, str]] = []
    for level, tendency in _fetch_distinct_combos(settings):
        _, cached_ts = _get_feed_cache(level, tendency, settings)
        if cached_ts is None or newest is None or cached_ts < newest:
            stale.append((level, tendency))

    if not stale:
        return 0

    # 보조지표는 (레벨,성향) 무관하게 동일 — 한 번만 계산
    indicators = _compute_top_tickers_indicators(articles)

    log_event(logger, logging.INFO, "digest_worker_regen_start",
              combo_count=len(stale), article_count=len(articles))

    def _process(combo: tuple[int, str]) -> None:
        level, tendency = combo
        result = _build_feed_digest(articles, indicators, level, tendency, settings)
        save_ticker_digest_cache(_FEED_SENTINEL, level, tendency, result, settings)

    processed = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_process, combo): combo for combo in stale}
        for future in as_completed(futures):
            level, tendency = futures[future]
            try:
                future.result()
                processed += 1
                log_event(logger, logging.INFO, "digest_worker_combo_done",
                          level=level, tendency=tendency)
            except Exception as exc:
                log_event(logger, logging.ERROR, "digest_worker_combo_failed",
                          level=level, tendency=tendency, error=str(exc))

    log_event(logger, logging.INFO, "digest_worker_regen_done",
              processed=processed, total=len(stale))
    return processed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Feed digest cache refresh worker")
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
