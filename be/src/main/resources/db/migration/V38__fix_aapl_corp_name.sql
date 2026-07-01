-- AAPL이 뉴스 엔티티 오태깅으로 'Microsoft Corp' 등 다른 회사명으로 박힌 것 즉시 교정.
-- 근본 원인(뉴스 companies 필드 신뢰 + ON CONFLICT DO NOTHING 영구고정)은
-- TickerDiscoveryService.reconcileCorpNames()가 SEC 공식명 기준으로 자가교정한다.
-- (원래 V35로 작성됐으나 프로덕션 미적용 상태였고, V36/V37 적용 이후라 순서 유지를 위해 V38로 재배포)
UPDATE ticker_names
SET corp = 'Apple Inc.', ko = '애플', aliases = ARRAY['apple', '애플', 'aapl']
WHERE ticker = 'AAPL' AND corp <> 'Apple Inc.';
