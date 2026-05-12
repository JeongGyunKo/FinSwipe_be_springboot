CREATE TABLE IF NOT EXISTS user_read_articles (
    user_id    UUID        NOT NULL,
    article_id UUID        NOT NULL REFERENCES news_articles(id) ON DELETE CASCADE,
    read_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, article_id)
);

CREATE INDEX IF NOT EXISTS idx_user_read_articles_user_id
    ON user_read_articles (user_id);
