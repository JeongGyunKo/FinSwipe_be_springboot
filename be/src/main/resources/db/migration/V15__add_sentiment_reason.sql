ALTER TABLE news_articles
    ADD COLUMN IF NOT EXISTS sentiment_reason TEXT;
