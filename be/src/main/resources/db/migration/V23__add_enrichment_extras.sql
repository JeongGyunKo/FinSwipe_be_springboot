ALTER TABLE news_articles
    ADD COLUMN IF NOT EXISTS event_category      TEXT,
    ADD COLUMN IF NOT EXISTS sentiment_divergence BOOLEAN,
    ADD COLUMN IF NOT EXISTS novelty_score        DOUBLE PRECISION;

CREATE INDEX IF NOT EXISTS idx_news_articles_event_category
    ON news_articles (event_category) WHERE event_category IS NOT NULL;
