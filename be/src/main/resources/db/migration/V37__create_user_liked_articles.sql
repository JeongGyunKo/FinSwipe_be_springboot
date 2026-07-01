-- 좋아요(오른쪽 스와이프 = 관심있음)한 기사 저장. user_disliked_articles(V36)와 대칭 구조.
-- (원래 V34로 작성됐으나 프로덕션 미적용 상태였고, V36 적용 이후라 순서 유지를 위해 V37로 재배포)
CREATE TABLE IF NOT EXISTS user_liked_articles (
    user_id    UUID        NOT NULL,
    article_id UUID        NOT NULL REFERENCES news_articles(id) ON DELETE CASCADE,
    liked_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, article_id)
);

CREATE INDEX IF NOT EXISTS idx_user_liked_articles_user_id
    ON user_liked_articles (user_id);
