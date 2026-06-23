-- 아이디(login_id) 정책을 대소문자 구분으로 전환.
-- V32에서 추가한 LOWER(login_id) 기준 UNIQUE 인덱스를 제거하고, 원본 케이스 기준 UNIQUE로 교체한다.
-- 주의: V32가 기존 데이터를 이미 소문자화했으므로 기존 아이디의 원래 대소문자는 복구되지 않는다
--       (register가 예전부터 소문자화해 와서 원본 케이스 정보가 이미 소실됨). 신규 가입부터 케이스 보존됨.
-- 현재 모든 login_id는 소문자라 LOWER 기준 유니크 = 원본 기준 유니크 → 일반 UNIQUE 인덱스 생성 안전.
DROP INDEX IF EXISTS idx_user_profiles_login_id_unique;

CREATE UNIQUE INDEX IF NOT EXISTS idx_user_profiles_login_id_unique_cs
    ON user_profiles (login_id) WHERE login_id IS NOT NULL;
