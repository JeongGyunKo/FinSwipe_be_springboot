-- V3에서 summary_3lines를 TEXT[]로 정의했으나 실제 운영 DB는 JSONB로 생성됨.
-- TEXT[]인 경우에만 JSONB로 변환 (이미 JSONB이면 무시).
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'news_articles'
          AND column_name = 'summary_3lines'
          AND data_type = 'ARRAY'
    ) THEN
        ALTER TABLE news_articles
            ALTER COLUMN summary_3lines TYPE JSONB USING to_jsonb(summary_3lines);
    END IF;
END $$;
