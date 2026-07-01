-- V44: 추천 성과 로그 — "개인화가 실제로 먹히는지" 측정용
-- 피드가 무엇을(article) 누구에게(user) 어떤 자격으로(source: personal/explore/cold) 노출했는지 기록.
-- 이후 좋아요/읽음/체류와 조인해 source별 관여도(engagement)를 비교 → 개인화 효과 검증.
-- (user, article, 날짜) 유니크로 하루 반복 새로고침이 행을 부풀리지 않게 제한(≈30행/유저/일).
CREATE TABLE IF NOT EXISTS recommendation_log (
    user_id     UUID        NOT NULL,
    article_id  UUID        NOT NULL,
    served_date DATE        NOT NULL DEFAULT (now() AT TIME ZONE 'America/New_York')::date,
    rank        INTEGER     NOT NULL,   -- 피드 내 위치(0-based)
    source      TEXT        NOT NULL,   -- personal | explore | cold
    score       DOUBLE PRECISION,       -- 랭킹 점수(참고용)
    served_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, article_id, served_date)
);

CREATE INDEX IF NOT EXISTS idx_reco_log_served_at ON recommendation_log (served_at DESC);
CREATE INDEX IF NOT EXISTS idx_reco_log_article   ON recommendation_log (article_id);
