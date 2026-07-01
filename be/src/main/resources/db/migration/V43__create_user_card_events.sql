-- V43: 카드 행동 이벤트 로그 (에이전트형 큐레이션 신호)
-- 좋아요/싫어요/읽음은 기존 전용 테이블(user_liked/disliked/read_articles)에 있고,
-- 여기엔 FE가 보내는 노출(impression)·체류(dwell)·열람(open)·건너뜀(skip) 신호를 append-only로 쌓는다.
-- news_articles FK를 걸지 않아(기사 정리와 무관) 수집을 가볍고 견고하게 유지.
CREATE TABLE IF NOT EXISTS user_card_events (
    id          BIGSERIAL   PRIMARY KEY,
    user_id     UUID        NOT NULL,
    article_id  UUID        NOT NULL,
    event_type  TEXT        NOT NULL,   -- impression | dwell | open | skip
    dwell_ms    INTEGER,                -- dwell 이벤트의 카드 체류 시간(ms)
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_user_card_events_user
    ON user_card_events (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_user_card_events_user_type
    ON user_card_events (user_id, event_type);
