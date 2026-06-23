-- 실제로는 상장폐지됐으나 ticker_names.delisted_at 이 NULL로 남아 활성 종목처럼 노출되던
-- 종목들을 실제 폐지일로 표기한다. 필터(delisted_at IS NULL)가 자동으로 토글 유니버스·피드·
-- 검색·챗봇 인식에서 제외한다.
-- ATVI(Activision Blizzard): 2023-10-13 Microsoft 인수로 NASDAQ 상장폐지.
UPDATE ticker_names
SET delisted_at = TIMESTAMPTZ '2023-10-13 00:00:00+00'
WHERE ticker = 'ATVI' AND delisted_at IS NULL;

-- 폐지 종목을 이미 담아둔 유저의 관심목록에서 제거 — 유니버스에서 빠지면 설정 화면에서
-- 해제(삭제)할 수 없는 orphan 으로 남기 때문. 배열 순서는 보존한다.
UPDATE user_profiles up
SET tickers = COALESCE((
        SELECT array_agg(t ORDER BY ord)
        FROM unnest(up.tickers) WITH ORDINALITY AS x(t, ord)
        WHERE t NOT IN (SELECT ticker FROM ticker_names WHERE delisted_at IS NOT NULL)
    ), '{}'::text[]),
    updated_at = NOW()
WHERE up.tickers && (SELECT array_agg(ticker) FROM ticker_names WHERE delisted_at IS NOT NULL);
