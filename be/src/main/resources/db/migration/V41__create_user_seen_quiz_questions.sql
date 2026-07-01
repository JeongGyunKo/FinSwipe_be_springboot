-- V38: 유저가 이미 푼 단일 퀴즈 문제 기록 (중복 출제 방지)
-- seen_at은 재활용 정렬용 — 풀 고갈 시 "가장 오래전 푼 문제"를 다시 낼 때 오래된 순으로 정렬.
CREATE TABLE IF NOT EXISTS user_seen_quiz_questions (
    user_id     UUID        NOT NULL,
    question_id UUID        NOT NULL REFERENCES quiz_single_questions(id) ON DELETE CASCADE,
    seen_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, question_id)
);

CREATE INDEX IF NOT EXISTS idx_user_seen_quiz_user
    ON user_seen_quiz_questions (user_id);
