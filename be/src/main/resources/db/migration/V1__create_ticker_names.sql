CREATE TABLE IF NOT EXISTS ticker_names (
    ticker TEXT PRIMARY KEY,
    corp   TEXT NOT NULL,
    ko     TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_ticker_names_ko
    ON ticker_names USING gin(to_tsvector('simple', ko));

CREATE INDEX IF NOT EXISTS idx_ticker_names_corp
    ON ticker_names USING gin(to_tsvector('simple', corp));
