-- Lock down GenAI operational tables for Supabase-style deployments.
--
-- Goal:
-- - Keep the tables for backend operation
-- - Prevent direct client access from anon/authenticated roles
-- - Allow backend/server-side access through privileged DB credentials
--
-- Notes:
-- - This script does NOT delete tables.
-- - It enables RLS and removes direct table privileges from client roles.
-- - With RLS enabled and no client-facing policies, anon/authenticated reads/writes are denied.

BEGIN;

REVOKE ALL ON TABLE public.raw_news FROM anon, authenticated;
REVOKE ALL ON TABLE public.raw_news_tickers FROM anon, authenticated;
REVOKE ALL ON TABLE public.enrichment_jobs FROM anon, authenticated;
REVOKE ALL ON TABLE public.enrichment_results FROM anon, authenticated;

ALTER TABLE public.raw_news ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.raw_news_tickers ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.enrichment_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.enrichment_results ENABLE ROW LEVEL SECURITY;

COMMIT;