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
        return repo.searchByName(query).stream()
                .map(TickerInfo::from)
                .collect(Collectors.toList());
    }

    public Optional<TickerInfo> getTickerInfo(String ticker) {
        return repo.findByTicker(ticker.toUpperCase()).map(TickerInfo::from);
    }

    /**
     * 티커 목록에 회사명 정보를 붙여서 반환 [{ticker, corp, ko}, ...]
     */
    public List<Map<String, String>> enrichTickers(List<String> tickers) {
        if (tickers == null || tickers.isEmpty()) return List.of();
        return tickers.stream()
                .map(t -> {
                    Optional<TickerName> info = repo.findByTicker(t);
                    Map<String, String> m = new java.util.HashMap<>();
                    m.put("ticker", t);
                    info.ifPresent(ti -> {
                        m.put("corp", ti.getCorp());
                        m.put("ko", ti.getKo());
                    });
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
