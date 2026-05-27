-- 한국어 완성 기사 조회 성능 개선
-- headline_ko/summary_3lines_ko/xai_ko 모두 있는 기사만 대상으로 partial index
-- findByXaiKoIsNotNullOrderByPublishedAtDesc, findUnreadByUser 쿼리 속도 향상
CREATE INDEX IF NOT EXISTS idx_news_articles_korean_published
    ON news_articles (published_at DESC)
    WHERE headline_ko IS NOT NULL
      AND summary_3lines_ko IS NOT NULL
      AND xai_ko IS NOT NULL;