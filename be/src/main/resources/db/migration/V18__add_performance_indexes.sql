-- V18: 성능 최적화 인덱스 추가

-- 뉴스 피드 조회용 부분 인덱스 (분석 완료된 기사만 대상)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_news_analyzed_published
    ON news_articles (published_at DESC)
    WHERE headline_ko IS NOT NULL
      AND summary_3lines_ko IS NOT NULL
      AND sentiment_reason IS NOT NULL;

-- 미분석 기사 조회용 부분 인덱스
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_news_unanalyzed
    ON news_articles (published_at DESC)
    WHERE content IS NOT NULL
      AND (sentiment_label IS NULL OR sentiment_label != '_clean_filtered')
      AND retry_count < 3;

-- 티커 배열 검색용 GIN 인덱스 (이미 존재하면 무시)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_news_tickers_gin
    ON news_articles USING GIN (tickers);

-- source_url 중복 체크 속도 개선
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_news_source_url
    ON news_articles (source_url);
