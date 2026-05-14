package com.finswipe.service;

import com.finswipe.config.CacheConfig;
import com.finswipe.domain.entity.TickerName;
import com.finswipe.domain.repository.TickerNameRepository;
import com.finswipe.dto.response.TickerInfo;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
@Slf4j
public class TickerService {

    private final TickerNameRepository repo;

    @Cacheable(CacheConfig.CACHE_TICKERS)
    public List<TickerInfo> getAllTickers() {
        log.info("Loading all tickers from DB");
        return repo.findAll().stream()
                .map(TickerInfo::from)
                .collect(Collectors.toList());
    }

    public List<TickerInfo> searchTickers(String query) {
        String escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_");
        return repo.searchByName(escaped).stream()
                .map(TickerInfo::from)
                .collect(Collectors.toList());
    }

    public Optional<TickerInfo> getTickerInfo(String ticker) {
        return repo.findByTicker(ticker.toUpperCase()).map(TickerInfo::from);
    }

    /**
     * 티커 목록에 회사명 정보를 붙여서 반환 [{ticker, corp, ko}, ...]
     * getAllTickers() 캐시 활용 — 기사당 DB 쿼리 없이 인메모리 조회 (60번 → 0번)
     */
    public List<Map<String, String>> enrichTickers(List<String> tickers) {
        if (tickers == null || tickers.isEmpty()) return List.of();
        Map<String, TickerInfo> infoMap = getAllTickers().stream()
                .collect(Collectors.toMap(TickerInfo::getTicker, t -> t));
        return tickers.stream()
                .map(t -> {
                    Map<String, String> m = new java.util.HashMap<>();
                    m.put("ticker", t);
                    TickerInfo info = infoMap.get(t);
                    if (info != null) {
                        m.put("corp", info.getCorp());
                        m.put("ko", info.getKo());
                    }
                    return m;
                })
                .collect(Collectors.toList());
    }

    /**
     * 검색된 티커들로 DB 티커 목록 반환 (뉴스 검색 전처리용)
     */
    public List<String> findMatchingTickerSymbols(String query) {
        return searchTickers(query).stream()
                .map(TickerInfo::getTicker)
                .collect(Collectors.toList());
    }
}
