-- Spring Boot Flyway V14 — 참고 사본
-- 실제 파일: src/main/resources/db/migration/V14__add_level_quiz_tables.sql
-- 이 파일은 GenAI 서버 독립 배포 시 psql로 직접 실행할 때 사용합니다.
-- (V5에서 login_id가 이미 추가되어 있으므로 여기선 level만 추가)

-- 1) user_profiles에 level 컬럼 추가
ALTER TABLE user_profiles
    ADD COLUMN IF NOT EXISTS level INTEGER DEFAULT NULL;

-- 2) 퀴즈 세션 테이블
CREATE TABLE IF NOT EXISTS quiz_sessions (
    id                  UUID        PRIMARY KEY,
    user_id             TEXT,
    current_difficulty  DOUBLE PRECISION NOT NULL DEFAULT 2.0,
    questions_asked     INTEGER     NOT NULL DEFAULT 0,
    correct_count       INTEGER     NOT NULL DEFAULT 0,
    status              TEXT        NOT NULL DEFAULT 'in_progress',
    final_level         INTEGER,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_quiz_sessions_user_id
    ON quiz_sessions (user_id)
    WHERE user_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_quiz_sessions_status
    ON quiz_sessions (status);

-- 3) 퀴즈 문항 테이블
CREATE TABLE IF NOT EXISTS quiz_questions (
    id              UUID        PRIMARY KEY,
    session_id      UUID        NOT NULL REFERENCES quiz_sessions(id) ON DELETE CASCADE,
    question_number INTEGER     NOT NULL,
    question_text   TEXT        NOT NULL,
    question_type   TEXT        NOT NULL DEFAULT 'multiple_choice',
    choices         JSONB       NOT NULL DEFAULT '{}',
    correct_answer  TEXT        NOT NULL,
    user_answer     TEXT,
    is_correct      BOOLEAN,
    explanation     TEXT,
    difficulty      DOUBLE PRECISION,
    topic           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_quiz_questions_session_id
    ON quiz_questions (session_id);
