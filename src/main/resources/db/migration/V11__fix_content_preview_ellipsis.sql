-- 기존 기사 content_preview에 말줄임표 추가 (300자로 잘렸고 .으로 안 끝나는 경우)
UPDATE news_articles
SET content_preview = content_preview || '...'
WHERE content_preview IS NOT NULL
  AND LENGTH(content) > 300
  AND RIGHT(content_preview, 1) != '.';