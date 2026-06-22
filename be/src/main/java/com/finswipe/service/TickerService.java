package com.finswipe.service;

import com.finswipe.config.CacheConfig;
import com.finswipe.domain.repository.TickerNameRepository;
import com.finswipe.dto.response.TickerInfo;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.sql.Array;
import java.sql.Date;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.stream.Collectors;

@Service
@RequiredArgsConstructor
@Slf4j
public class TickerService {

    private final TickerNameRepository repo;
    private final JdbcTemplate jdbc;

    // self-invocation 시 @Cacheable 우회 방지 — 앱 생명주기 동안 유효한 필드 캐시
    private volatile Map<String, TickerInfo> tickerInfoCache = null;

    private Map<String, TickerInfo> getTickerInfoCache() {
        if (tickerInfoCache == null) {
            synchronized (this) {
                if (tickerInfoCache == null) {
                    tickerInfoCache = loadActiveTickersFromDb();
                    log.info("[티커 캐시] {}개 로드", tickerInfoCache.size());
                }
            }
        }
        return tickerInfoCache;
    }

    /** 상장폐지(delisted_at IS NOT NULL) 제외한 활성 종목만 로드. aliases·delisting_date 포함. */
    private Map<String, TickerInfo> loadActiveTickersFromDb() {
        return jdbc.query(
                "SELECT ticker, corp, ko, aliases, delisting_date FROM ticker_names WHERE delisted_at IS NULL",
                (rs, i) -> {
                    String ticker = rs.getString("ticker");
                    String corp   = rs.getString("corp");
                    String ko     = rs.getString("ko");
                    List<String> aliases = List.of();
                    Array arr = rs.getArray("aliases");
                    if (arr != null) {
                        Object raw = arr.getArray();
                        if (raw instanceof String[] sa) aliases = Arrays.asList(sa);
                    }
                    Date delistingDateSql = rs.getDate("delisting_date");
                    LocalDate delistingDate = delistingDateSql != null ? delistingDateSql.toLocalDate() : null;
                    return new TickerInfo(ticker, corp, ko, aliases, delistingDate);
                }
        ).stream().collect(Collectors.toMap(TickerInfo::getTicker, t -> t));
    }

    /** 캐시 무효화 — 신규 티커 추가/상장폐지 처리 후 호출 */
    public void invalidateCache() {
        synchronized (this) {
            tickerInfoCache = null;
        }
    }

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
     * 필드 캐시 사용 — self-invocation으로 @Cacheable 우회되는 문제 해결 (23번 DB 쿼리 → 1번)
     */
    public List<Map<String, String>> enrichTickers(List<String> tickers) {
        if (tickers == null || tickers.isEmpty()) return List.of();
        Map<String, TickerInfo> infoMap = getTickerInfoCache();
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

    /**
     * 메시지 텍스트에 등장한 티커 — 한글명/심볼(단어 단위)/영문 사명 매칭. 챗봇 라우팅용.
     * 가장 구체적인(한글명이 긴) 매칭이 앞에 오도록 정렬.
     */
    public List<TickerInfo> findMentionedTickers(String text) {
        if (text == null || text.isBlank()) return List.of();
        String upper = text.toUpperCase();
        Set<String> tokens = new HashSet<>(Arrays.asList(upper.split("[^A-Z0-9]+")));
        List<TickerInfo> matches = new ArrayList<>();
        for (TickerInfo info : getTickerInfoCache().values()) {
            String ko = info.getKo();
            String corp = info.getCorp();
            String sym = info.getTicker();
            boolean hit = (ko != null && ko.length() >= 2 && text.contains(ko))
                    || (sym != null && sym.length() >= 2 && tokens.contains(sym))
                    || (corp != null && corp.length() >= 5 && upper.contains(corp.toUpperCase()))
                    || info.getAliases().stream().anyMatch(a -> a.length() >= 2 && text.contains(a));
            if (hit) matches.add(info);
        }
        matches.sort((a, b) -> {
            int la = a.getKo() != null ? a.getKo().length() : 0;
            int lb = b.getKo() != null ? b.getKo().length() : 0;
            return Integer.compare(lb, la);
        });
        return matches;
    }
}
