-- V23이 Flyway에 성공으로 기록됐으나 실제 컬럼이 없는 경우를 위한 보정 마이그레이션
ALTER TABLE news_articles
    ADD COLUMN IF NOT EXISTS event_category      TEXT,
    ADD COLUMN IF NOT EXISTS sentiment_divergence BOOLEAN,
    ADD COLUMN IF NOT EXISTS novelty_score        DOUBLE PRECISION;

CREATE INDEX IF NOT EXISTS idx_news_articles_event_category
    ON news_articles (event_category) WHERE event_category IS NOT NULL;
