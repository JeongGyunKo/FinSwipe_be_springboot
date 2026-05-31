-- V16: 자체 인증 시스템 컬럼 추가
ALTER TABLE user_profiles
    ADD COLUMN IF NOT EXISTS password_hash       TEXT,
    ADD COLUMN IF NOT EXISTS auth_provider       TEXT NOT NULL DEFAULT 'email',
    ADD COLUMN IF NOT EXISTS email_verified      BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS email_verify_token  TEXT,
    ADD COLUMN IF NOT EXISTS google_sub          TEXT,
    ADD COLUMN IF NOT EXISTS password_reset_token   TEXT,
    ADD COLUMN IF NOT EXISTS password_reset_expires TIMESTAMPTZ;

CREATE UNIQUE INDEX IF NOT EXISTS idx_user_profiles_email
    ON user_profiles (email) WHERE email IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_user_profiles_google_sub
    ON user_profiles (google_sub) WHERE google_sub IS NOT NULL;
