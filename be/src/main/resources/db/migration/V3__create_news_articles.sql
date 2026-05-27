CREATE TABLE IF NOT EXISTS news_articles (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    headline          TEXT        NOT NULL,
    summary           TEXT,
    summary_3lines    TEXT[],
    source_url        TEXT        UNIQUE NOT NULL,
    content           TEXT,
    image_url         TEXT,
    published_at      TIMESTAMPTZ,
    categories        TEXT[],
    countries         TEXT[],
    tickers           TEXT[],
    is_paywalled      BOOLEAN     NOT NULL DEFAULT FALSE,

    -- GenAI enrichment
    sentiment_label   TEXT,
    sentiment_score   DOUBLE PRECISION,
    xai               JSONB,
    is_mixed          BOOLEAN,

    -- Korean localization
    headline_ko       TEXT,
    summary_3lines_ko TEXT[],
    xai_ko            JSONB,

    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_news_articles_published_at
    ON news_articles (published_at DESC);

CREATE INDEX IF NOT EXISTS idx_news_articles_tickers
    ON news_articles USING gin(tickers);

CREATE INDEX IF NOT EXISTS idx_news_articles_sentiment
    ON news_articles (sentiment_label)
    WHERE sentiment_label IS NULL;
