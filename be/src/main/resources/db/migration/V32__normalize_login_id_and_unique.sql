-- login_id 대소문자 정규화 + 대소문자 무시 UNIQUE 보장.
-- 그동안 register는 소문자화했으나 updateProfile은 안 해서 'John'/'john' 변형 중복이 가능했고,
-- login_id에 UNIQUE 제약이 없어(일반 인덱스만) 동시 가입 레이스로도 중복이 생길 수 있었음.

-- 1) 소문자화 시 충돌하는 변형: 가장 먼저 만든 계정만 유지하고, 나머지는 계정 id를 접미사로 붙여 분리
--    (계정 id는 UUID라 충돌이 절대 없음 — 인덱스 생성 실패 방지)
WITH ranked AS (
    SELECT id,
           ROW_NUMBER() OVER (PARTITION BY LOWER(login_id) ORDER BY created_at, id) AS rn
    FROM user_profiles
    WHERE login_id IS NOT NULL
)
UPDATE user_profiles up
SET login_id = LOWER(up.login_id) || '_' || up.id::text
FROM ranked r
WHERE up.id = r.id AND r.rn > 1;

-- 2) 충돌 없던 나머지 login_id 전부 소문자화
UPDATE user_profiles
SET login_id = LOWER(login_id)
WHERE login_id IS NOT NULL AND login_id <> LOWER(login_id);

-- 3) 대소문자 무시 UNIQUE 인덱스 (email/google_sub와 동일하게 부분 인덱스)
CREATE UNIQUE INDEX IF NOT EXISTS idx_user_profiles_login_id_unique
    ON user_profiles (LOWER(login_id)) WHERE login_id IS NOT NULL;
