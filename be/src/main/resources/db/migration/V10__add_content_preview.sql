ALTER TABLE news_articles ADD COLUMN IF NOT EXISTS content_preview TEXT;

-- 기존 기사 원문 300자 미리보기 채우기
UPDATE news_articles
SET content_preview = LEFT(content, 300)
WHERE content IS NOT NULL AND content_preview IS NULL;
