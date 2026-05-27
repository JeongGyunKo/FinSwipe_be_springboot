-- news_articles 테이블에 updated_at 컬럼 추가 (V3에 정의됐지만 실제 DB에 누락됨)
ALTER TABLE news_articles ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();