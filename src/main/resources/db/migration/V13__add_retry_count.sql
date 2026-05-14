-- 재분석 시도 횟수 추적 — 3회 실패 시 재분석 대상에서 제외
ALTER TABLE news_articles ADD COLUMN IF NOT EXISTS retry_count INTEGER NOT NULL DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_news_articles_retry_count
    ON news_articles (retry_count)
    WHERE retry_count > 0;