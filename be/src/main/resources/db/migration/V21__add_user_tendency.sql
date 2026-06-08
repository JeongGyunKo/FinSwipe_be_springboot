-- V21: user_profiles에 tendency 컬럼 추가 (퀴즈 완료 시 자동 반영)
ALTER TABLE user_profiles
    ADD COLUMN IF NOT EXISTS tendency TEXT;
