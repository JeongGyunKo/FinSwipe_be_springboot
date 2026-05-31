-- V17: 미사용 컬럼 제거
-- xai/xai_ko: XAI 비활성화로 더 이상 채워지지 않음
-- summary: summary_3lines로 대체됨
ALTER TABLE news_articles
    DROP COLUMN IF EXISTS xai,
    DROP COLUMN IF EXISTS xai_ko,
    DROP COLUMN IF EXISTS summary;
