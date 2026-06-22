ALTER TABLE ticker_names
    ADD COLUMN IF NOT EXISTS aliases    TEXT[]      NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS delisted_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_ticker_names_delisted ON ticker_names (delisted_at) WHERE delisted_at IS NOT NULL;
