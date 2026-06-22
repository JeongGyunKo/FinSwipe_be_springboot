package com.finswipe.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;

import java.net.URI;
import java.time.LocalDate;

import java.util.*;
import java.util.stream.Collectors;

/**
 * 신규 상장 종목 자동 감지 및 상장폐지 종목 처리.
 * - 뉴스 수집 시 companies 필드에서 ticker_names에 없는 신규 티커 발견 → GenAI 번역 → DB 저장
 * - 주기적으로 전체 종목 가격 조회 → 실패 시 delisted_at 플래그
 */
@Service
@Slf4j
public class TickerDiscoveryService {

    private volatile Map<String, String> cikCache = null;

    private final JdbcTemplate jdbc;
    private final ObjectMapper objectMapper;
    private final TickerService tickerService;
    private final RestClient genaiClient;
    private final RestClient secEdgarClient;

    public TickerDiscoveryService(JdbcTemplate jdbc,
                                  ObjectMapper objectMapper,
                                  TickerService tickerService,
                                  @Qualifier("genaiRestClient") RestClient genaiClient,
                                  @Qualifier("secEdgarRestClient") RestClient secEdgarClient) {
        this.jdbc = jdbc;
        this.objectMapper = objectMapper;
        this.tickerService = tickerService;
        this.genaiClient = genaiClient;
        this.secEdgarClient = secEdgarClient;
    }

    /**
     * 뉴스 수집 결과의 companies 목록에서 ticker_names에 없는 신규 티커를 감지해 DB에 등록.
     * ticker → corp(영문 회사명) 맵을 받는다.
     */
    public void discoverNewTickers(Map<String, String> tickerCorpMap) {
        if (tickerCorpMap.isEmpty()) return;

        Set<String> known = new HashSet<>(
                jdbc.queryForList("SELECT ticker FROM ticker_names", String.class));

        Map<String, String> newOnes = tickerCorpMap.entrySet().stream()
                .filter(e -> !known.contains(e.getKey()))
                .collect(Collectors.toMap(Map.Entry::getKey, Map.Entry::getValue));

        if (newOnes.isEmpty()) return;
        log.info("[티커 감지] 신규 {} 종목 발견: {}", newOnes.size(), newOnes.keySet());

        for (Map.Entry<String, String> entry : newOnes.entrySet()) {
            try {
                registerTicker(entry.getKey(), entry.getValue());
            } catch (Exception e) {
                log.warn("[티커 감지] {} 등록 실패: {}", entry.getKey(), e.getMessage());
            }
        }
    }

    private void registerTicker(String ticker, String corp) {
        TranslateResult result = translateWithGenAi(ticker, corp);
        String ko = result.ko();
        List<String> aliases = result.aliases();

        jdbc.update(conn -> {
            var ps = conn.prepareStatement(
                    "INSERT INTO ticker_names (ticker, corp, ko, aliases) VALUES (?, ?, ?, ?) ON CONFLICT (ticker) DO NOTHING");
            ps.setString(1, ticker);
            ps.setString(2, corp);
            ps.setString(3, ko);
            ps.setArray(4, conn.createArrayOf("text", aliases.toArray()));
            return ps;
        });

        tickerService.invalidateCache();
        log.info("[티커 등록] {} → ko={} aliases={}", ticker, ko, aliases);
    }

    private TranslateResult translateWithGenAi(String ticker, String corp) {
        try {
            Map<String, String> body = Map.of("ticker", ticker, "corp", corp);
            String raw = genaiClient.post()
                    .uri("/api/v1/ticker-names/translate")
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(objectMapper.writeValueAsString(body))
                    .retrieve()
                    .body(String.class);

            JsonNode node = objectMapper.readTree(raw);
            String ko = node.path("ko").asText(corp);
            List<String> aliases = new ArrayList<>();
            node.path("aliases").forEach(n -> aliases.add(n.asText()));
            return new TranslateResult(ko.isBlank() ? corp : ko, aliases);
        } catch (Exception e) {
            log.warn("[티커 번역] GenAI 실패 ({}/{}), 영문명 사용: {}", ticker, corp, e.getMessage());
            return new TranslateResult(corp, List.of(ticker.toLowerCase()));
        }
    }

    /**
     * 매일 UTC 22:00 (미국 장 마감 2시간 후) — 나스닥+NYSE 현재 상장 목록과 DB를 대조.
     * 목록에서 사라진 종목 = 상장폐지 확정 → Form 25로 예정일 조회 후 처리.
     * 오탐 없음: 목록 자체가 현재 상장 여부의 공식 기준.
     */
    @Scheduled(cron = "0 0 22 * * *")
    public void syncListingStatus() {
        Set<String> listed = fetchListedTickers();
        if (listed.isEmpty()) {
            log.error("[상장 동기화] 나스닥/NYSE 목록 조회 실패 — 스킵");
            return;
        }

        List<String> activeTickers = jdbc.queryForList(
                "SELECT ticker FROM ticker_names WHERE delisted_at IS NULL AND delisting_date IS NULL",
                String.class);

        List<String> gone = activeTickers.stream()
                .filter(t -> !listed.contains(t.toUpperCase()))
                .toList();

        if (gone.isEmpty()) {
            log.info("[상장 동기화] 신규 상장폐지 없음 (체크: {}개)", activeTickers.size());
            return;
        }

        log.info("[상장 동기화] {}개 목록 이탈 감지 → Form 25 예정일 조회", gone.size());
        Map<String, String> cikMap = getCikMap();
        int processed = 0;

        for (String ticker : gone) {
            LocalDate delistingDate = fetchDelistingDateFromSec(ticker, cikMap);
            if (delistingDate != null && delistingDate.isAfter(LocalDate.now())) {
                setDelistingDate(ticker, delistingDate);
                log.info("[상장폐지 예정] {} → {}", ticker, delistingDate);
            } else {
                markDelisted(ticker);
            }
            processed++;
        }

        if (processed > 0) tickerService.invalidateCache();
        log.info("[상장 동기화] {}개 처리 완료", processed);
    }

    /** 나스닥+NYSE 현재 상장 종목 심볼 전체 반환 */
    private Set<String> fetchListedTickers() {
        Set<String> result = new HashSet<>();
        for (String exchange : List.of("nasdaq", "nyse")) {
            try {
                String url = "https://api.nasdaq.com/api/screener/stocks?tableonly=true&exchange="
                        + exchange + "&download=true";
                String raw = secEdgarClient.get()
                        .uri(URI.create(url))
                        .header("User-Agent", "Mozilla/5.0")
                        .retrieve()
                        .body(String.class);
                JsonNode root = objectMapper.readTree(raw);
                root.path("data").path("rows").forEach(row -> {
                    String sym = row.path("symbol").asText("").toUpperCase().trim();
                    if (!sym.isEmpty()) result.add(sym);
                });
                log.info("[상장 목록] {} {}개", exchange.toUpperCase(), result.size());
            } catch (Exception e) {
                log.error("[상장 목록] {} 조회 실패: {}", exchange, e.getMessage());
            }
        }
        return result;
    }

    /** 목록에서 사라진 종목의 Form 25 신청일 + 10일 = 상장폐지 예정일 반환. 없으면 null. */
    private LocalDate fetchDelistingDateFromSec(String ticker, Map<String, String> cikMap) {
        String cik = cikMap.get(ticker.toUpperCase());
        if (cik == null) return null;
        try {
            String url = "https://data.sec.gov/submissions/CIK" + cik + ".json";
            String raw = secEdgarClient.get().uri(URI.create(url)).retrieve().body(String.class);
            JsonNode root = objectMapper.readTree(raw);
            JsonNode forms = root.path("filings").path("recent").path("form");
            JsonNode dates = root.path("filings").path("recent").path("filingDate");
            for (int i = 0; i < forms.size(); i++) {
                String form = forms.get(i).asText();
                if ("25".equals(form) || "25-NSE".equals(form)) {
                    String dateStr = dates.get(i).asText(null);
                    if (dateStr != null) return LocalDate.parse(dateStr).plusDays(10);
                }
            }
        } catch (Exception e) {
            log.warn("[Form 25] {} 예정일 조회 실패: {}", ticker, e.getMessage());
        }
        return null;
    }

    /** 티커→CIK 맵 (앱 수명 동안 캐시, 첫 호출 시 SEC에서 다운로드) */
    private Map<String, String> getCikMap() {
        if (cikCache == null) {
            synchronized (this) {
                if (cikCache == null) cikCache = loadCikMap();
            }
        }
        return cikCache;
    }

    private Map<String, String> loadCikMap() {
        try {
            String raw = secEdgarClient.get()
                    .uri(URI.create("https://www.sec.gov/files/company_tickers.json"))
                    .retrieve()
                    .body(String.class);
            JsonNode root = objectMapper.readTree(raw);
            Map<String, String> map = new HashMap<>();
            root.properties().forEach(e -> {
                JsonNode v = e.getValue();
                String ticker = v.path("ticker").asText("");
                long cikLong = v.path("cik_str").asLong(0);
                if (!ticker.isEmpty() && cikLong > 0)
                    map.put(ticker.toUpperCase(), String.format("%010d", cikLong));
            });
            log.info("[CIK 맵] {}개 로드 완료", map.size());
            return map;
        } catch (Exception e) {
            log.error("[CIK 맵] 로드 실패: {}", e.getMessage());
            return Map.of();
        }
    }

    /** 매일 UTC 22:10 — delisting_date가 오늘 이하인 종목을 delisted_at으로 확정 처리 */
    @Scheduled(cron = "0 10 22 * * *")
    public void confirmDelistedTickers() {
        int updated = jdbc.update(
                "UPDATE ticker_names SET delisted_at = NOW() WHERE delisting_date <= CURRENT_DATE AND delisted_at IS NULL");
        if (updated > 0) {
            tickerService.invalidateCache();
            log.info("[상장폐지 확정] {}개 종목 캐시에서 제거", updated);
        }
    }

    private void markDelisted(String ticker) {
        jdbc.update("UPDATE ticker_names SET delisted_at = NOW() WHERE ticker = ? AND delisted_at IS NULL", ticker);
        log.info("[상장폐지] {} → delisted_at 기록", ticker);
    }

    private void setDelistingDate(String ticker, LocalDate date) {
        jdbc.update("UPDATE ticker_names SET delisting_date = ? WHERE ticker = ? AND delisting_date IS NULL",
                date, ticker);
    }

    private record TranslateResult(String ko, List<String> aliases) {}
}
