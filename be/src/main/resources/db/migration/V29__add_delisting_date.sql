ALTER TABLE ticker_names
    ADD COLUMN IF NOT EXISTS delisting_date DATE;

CREATE INDEX IF NOT EXISTS idx_ticker_names_delisting ON ticker_names (delisting_date)
    WHERE delisting_date IS NOT NULL AND delisted_at IS NULL;
