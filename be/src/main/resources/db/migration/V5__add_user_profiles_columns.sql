-- login_id: /auth/find-email, /auth/find-login-id 엔드포인트에서 사용
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS login_id TEXT;

-- tickers: 관심 종목 목록, FCM 알림 대상 사용자 필터링에 사용
ALTER TABLE user_profiles ADD COLUMN IF NOT EXISTS tickers TEXT[] DEFAULT '{}';

CREATE INDEX IF NOT EXISTS idx_user_profiles_login_id
    ON user_profiles (login_id);

CREATE INDEX IF NOT EXISTS idx_user_profiles_tickers
    ON user_profiles USING gin(tickers);