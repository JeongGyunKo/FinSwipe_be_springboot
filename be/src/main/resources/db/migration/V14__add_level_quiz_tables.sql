-- V14: 사용자 레벨 컬럼 추가 + 퀴즈 테이블 신규 생성 (GenAI 서버용)

-- 1) user_profiles에 level 컬럼 추가
ALTER TABLE user_profiles
    ADD COLUMN IF NOT EXISTS level INTEGER DEFAULT NULL;

-- 2) 퀴즈 세션 테이블
CREATE TABLE IF NOT EXISTS quiz_sessions (
    id                  UUID        PRIMARY KEY,
    user_id             TEXT,                                  -- user_profiles.id (nullable: 비로그인 허용)
    current_difficulty  DOUBLE PRECISION NOT NULL DEFAULT 2.0,
    questions_asked     INTEGER     NOT NULL DEFAULT 0,
    correct_count       INTEGER     NOT NULL DEFAULT 0,
    status              TEXT        NOT NULL DEFAULT 'in_progress', -- in_progress | completed | abandoned
    final_level         INTEGER,                               -- 1~5, 완료 시 설정
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
    question_type   TEXT        NOT NULL DEFAULT 'multiple_choice', -- multiple_choice | ox
    choices         JSONB       NOT NULL DEFAULT '{}',
    correct_answer  TEXT        NOT NULL,
    user_answer     TEXT,
    is_correct      BOOLEAN,
    explanation     TEXT,
    difficulty      DOUBLE PRECISION,
    topic           TEXT,                                      -- 중복 출제 방지용 키워드
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_quiz_questions_session_id
    ON quiz_questions (session_id);
