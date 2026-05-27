CREATE TABLE IF NOT EXISTS user_profiles (
    id           UUID PRIMARY KEY,
    email        TEXT,
    display_name TEXT,
    avatar_url   TEXT,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);
