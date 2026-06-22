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
import java.time.format.DateTimeFormatter;
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

    // 전체 URL 사용 — 상대 경로 + baseUrl 조합 시 이중 인코딩 방지
    private static final String SEC_EDGAR_TICKER_FORM25 =
            "https://efts.sec.gov/LATEST/search-index?q=%%22%s%%22&forms=25&dateRange=custom&startdt=%s&enddt=%s";

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
     * 매일 UTC 22:00 (미국 장 마감 2시간 후) — 활성 종목 각각을 SEC EDGAR Form 25에서 직접 검색.
     * Form 25의 period_of_report(상장폐지 예정일)를 delisting_date에 저장.
     * delisted_at은 예정일 당일 confirmDelistedTickers()가 기록한다.
     */
    @Scheduled(cron = "0 0 22 * * *")
    public void detectDelistedTickersFromSec() {
        String today = LocalDate.now().format(DateTimeFormatter.ISO_LOCAL_DATE);
        String startdt = LocalDate.now().minusYears(10).format(DateTimeFormatter.ISO_LOCAL_DATE);

        // delisting_date가 이미 기록된 종목은 재검색 불필요
        List<String> activeTickers = jdbc.queryForList(
                "SELECT ticker FROM ticker_names WHERE delisted_at IS NULL AND delisting_date IS NULL",
                String.class);

        int detected = 0;
        for (String ticker : activeTickers) {
            try {
                String url = String.format(SEC_EDGAR_TICKER_FORM25, ticker, startdt, today);
                String raw = secEdgarClient.get().uri(URI.create(url)).retrieve().body(String.class);
                JsonNode root = objectMapper.readTree(raw);
                int total = root.path("hits").path("total").path("value").asInt(0);
                if (total > 0) {
                    // hits 중 가장 최근 period_of_report를 상장폐지 예정일로 사용
                    JsonNode firstHit = root.path("hits").path("hits").get(0);
                    String periodStr = firstHit != null
                            ? firstHit.path("_source").path("period_of_report").asText(null) : null;
                    LocalDate delistingDate = null;
                    if (periodStr != null && !periodStr.isBlank()) {
                        try { delistingDate = LocalDate.parse(periodStr); } catch (Exception ignored) {}
                    }
                    if (delistingDate == null) delistingDate = LocalDate.now().plusDays(10);
                    setDelistingDate(ticker, delistingDate);
                    detected++;
                    log.info("[SEC EDGAR] 상장폐지 예정 감지: {} → {}", ticker, delistingDate);
                }
                Thread.sleep(300);
            } catch (InterruptedException ie) {
                Thread.currentThread().interrupt();
                break;
            } catch (Exception e) {
                log.warn("[SEC EDGAR] {} 조회 실패: {}", ticker, e.getMessage());
            }
        }

        if (detected > 0) tickerService.invalidateCache();
        log.info("[SEC EDGAR] Form 25 체크 완료 — {}개 상장폐지 예정 감지", detected);
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

    private void setDelistingDate(String ticker, LocalDate date) {
        jdbc.update("UPDATE ticker_names SET delisting_date = ? WHERE ticker = ? AND delisting_date IS NULL",
                date, ticker);
    }

    private record TranslateResult(String ko, List<String> aliases) {}
}
