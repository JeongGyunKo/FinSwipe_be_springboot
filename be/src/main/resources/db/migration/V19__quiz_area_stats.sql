-- V19: 퀴즈 영역별 스탯 컬럼 추가 (레벨 → 오각형 스탯 전환)
ALTER TABLE quiz_sessions
    ADD COLUMN IF NOT EXISTS area_stats      JSONB DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS analysis_depth  TEXT  DEFAULT 'basic';

ALTER TABLE quiz_questions
    ADD COLUMN IF NOT EXISTS area TEXT;
