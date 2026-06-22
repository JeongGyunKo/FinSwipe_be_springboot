ALTER TABLE news_articles
    ADD COLUMN IF NOT EXISTS price_at_collection NUMERIC(12, 4);
