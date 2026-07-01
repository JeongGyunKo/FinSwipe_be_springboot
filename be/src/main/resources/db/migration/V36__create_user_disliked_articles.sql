-- 싫어요(왼쪽 스와이프 = 관심없음)한 기사 저장. user_liked_articles와 대칭 구조.
CREATE TABLE IF NOT EXISTS user_disliked_articles (
    user_id      UUID        NOT NULL,
    article_id   UUID        NOT NULL REFERENCES news_articles(id) ON DELETE CASCADE,
    disliked_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, article_id)
);

CREATE INDEX IF NOT EXISTS idx_user_disliked_articles_user_id
    ON user_disliked_articles (user_id);
