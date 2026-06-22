package com.finswipe.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;

import java.util.*;
import java.util.stream.Collectors;

/**
 * 신규 상장 종목 자동 감지 및 상장폐지 종목 처리.
 * - 뉴스 수집 시 companies 필드에서 ticker_names에 없는 신규 티커 발견 → GenAI 번역 → DB 저장
 * - 주기적으로 전체 종목 가격 조회 → 실패 시 delisted_at 플래그
 */
@Service
@RequiredArgsConstructor
@Slf4j
public class TickerDiscoveryService {

    private final JdbcTemplate jdbc;
    private final ObjectMapper objectMapper;
    private final TickerService tickerService;
    private final TechnicalsService technicalsService;
    @Qualifier("genaiRestClient")
    private final RestClient genaiClient;

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
     * 매일 새벽 0시 UTC (오전 9시 KST) — 전체 활성 종목의 가격 조회를 시도해
     * N회 연속 실패 시 delisted_at을 기록한다.
     */
    @Scheduled(cron = "0 0 0 * * *")
    public void detectDelistedTickers() {
        List<String> tickers;
        try {
            tickers = jdbc.queryForList(
                    "SELECT ticker FROM ticker_names WHERE delisted_at IS NULL", String.class);
        } catch (Exception e) {
            log.error("[상장폐지 감지] 티커 목록 조회 실패: {}", e.getMessage());
            return;
        }

        int delisted = 0;
        for (String ticker : tickers) {
            try {
                TechnicalsService.TechnicalsData td = technicalsService.getTechnicals(ticker);
                if (td == null || td.currentPrice() == null) {
                    markDelisted(ticker);
                    delisted++;
                }
            } catch (Exception e) {
                log.debug("[상장폐지 감지] {} 조회 오류: {}", ticker, e.getMessage());
            }
        }

        if (delisted > 0) {
            tickerService.invalidateCache();
            log.info("[상장폐지 감지] {}개 종목 상장폐지 처리", delisted);
        }
    }

    private void markDelisted(String ticker) {
        jdbc.update("UPDATE ticker_names SET delisted_at = NOW() WHERE ticker = ? AND delisted_at IS NULL", ticker);
        log.info("[상장폐지] {} → delisted_at 기록", ticker);
    }

    private record TranslateResult(String ko, List<String> aliases) {}
}
