-- V37: 피드 삽입용 단일 퀴즈 문제 풀 (무상태, 레벨·영역 태깅)
-- 온보딩용 quiz_questions(세션 종속)와는 완전히 별개. 카드 피드 사이 인터스티셜로 1문제씩 노출.
CREATE TABLE IF NOT EXISTS quiz_single_questions (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    level          INTEGER     NOT NULL CHECK (level BETWEEN 1 AND 5),
    area           TEXT        NOT NULL,   -- 기본개념 | 마켓수급 | 매크로 | 펀더멘털 | 리스크관리
    question_text  TEXT        NOT NULL,
    choices        JSONB       NOT NULL DEFAULT '{}',   -- {"A":"...","B":"...","C":"...","D":"..."}
    correct_answer TEXT        NOT NULL,   -- 예: "B"
    explanation    TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_quiz_single_questions_level
    ON quiz_single_questions (level);
