CREATE TABLE IF NOT EXISTS device_tokens (
    id          BIGSERIAL   PRIMARY KEY,
    user_id     UUID        NOT NULL,
    token       TEXT        NOT NULL,
    platform    TEXT        NOT NULL DEFAULT 'web',
    notify_all_news BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_device_tokens_user_token UNIQUE (user_id, token)
);

CREATE INDEX IF NOT EXISTS idx_device_tokens_user_id
    ON device_tokens (user_id);