package com.finswipe.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.finswipe.domain.entity.NewsArticle;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientResponseException;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Semaphore;

@Service
@Slf4j
public class AnalyzerService {

    private final RestClient genaiClient;
    private final ExecutorService enrichmentExecutor;
    private final ObjectMapper objectMapper;
    // Python: asyncio.Semaphore(1) — 한 번에 1개씩 순차 제출, 3초 간격
    private final Semaphore submitSemaphore = new Semaphore(1);

    public AnalyzerService(@Qualifier("genaiRestClient") RestClient genaiClient,
                           @Qualifier("enrichmentExecutor") ExecutorService enrichmentExecutor,
                           ObjectMapper objectMapper) {
        this.genaiClient = genaiClient;
        this.enrichmentExecutor = enrichmentExecutor;
        this.objectMapper = objectMapper;
    }

    /** Python: check_genai_health() */
    public Map<String, String> checkHealth() {
        try {
            genaiClient.get().uri("/health").retrieve().toBodilessEntity();
            return Map.of("status", "ok");
        } catch (RestClientResponseException e) {
            int code = e.getStatusCode().value();
            if (code == 503) return Map.of("status", "suspended", "reason", "서버 일시 중단");
            return Map.of("status", "error", "code", String.valueOf(code));
        } catch (Exception e) {
            String msg = e.getMessage();
            if (msg != null && msg.contains("timed out")) {
                return Map.of("status", "offline", "reason", "응답 시간 초과");
            }
            return Map.of("status", "offline", "reason", "연결 불가");
        }
    }

    /** Python: analyze_news_batch() */
    public List<EnrichmentResult> analyzeBatch(List<NewsArticle> articles) {
        List<NewsArticle> valid = articles.stream()
                .filter(a -> a.getSourceUrl() != null && !a.getSourceUrl().isBlank()
                        && a.getContent() != null && !a.getContent().isBlank())
                .toList();

        log.info("[GenAI] enrichment 시작 → {}개", valid.size());

        List<CompletableFuture<EnrichmentResult>> futures = valid.stream()
                .map(article -> CompletableFuture.supplyAsync(() -> {
                    try {
                        submitSemaphore.acquire();
                        try {
                            Thread.sleep(3000);
                            return enrichSingle(article);
                        } finally {
                            submitSemaphore.release();
                        }
                    } catch (InterruptedException e) {
                        Thread.currentThread().interrupt();
                        return EnrichmentResult.unavailable(article.getSourceUrl());
                    }
                }, enrichmentExecutor))
                .toList();

        return futures.stream()
                .map(f -> {
                    try { return f.join(); }
                    catch (Exception e) {
                        log.error("Enrichment future failed", e);
                        return EnrichmentResult.unavailable(null);
                    }
                })
                .toList();
    }

    /** Python: _enrich_one() 내부 로직 */
    public EnrichmentResult enrichSingle(NewsArticle article) {
        String link = article.getSourceUrl();
        if (link == null) return EnrichmentResult.unavailable(null);
        link = link.replaceAll("/$", "");

        String content = article.getContent();
        if (content == null || content.isBlank()) {
            log.warn("[GenAI] 원문 없음 → 스킵: {}", truncate(link));
            return EnrichmentResult.unavailable(link);
        }

        // Python: cache_buster = f"?d={date.today().isoformat()}"
        String cacheBuster = "?d=" + LocalDate.now();
        Map<String, Object> body = new HashMap<>();
        body.put("news_id", link + cacheBuster);
        body.put("title", article.getHeadline() != null ? article.getHeadline() : "");
        body.put("link", link + cacheBuster);
        body.put("article_text", content.strip());
        if (article.getSummary() != null && !article.getSummary().isBlank()) {
            body.put("summary_text", article.getSummary().strip());
        }
        if (article.getTickers() != null && !article.getTickers().isEmpty()) {
            body.put("ticker", article.getTickers());
        }

        try {
            String rawResponse = genaiClient.post()
                    .uri("/api/v1/articles/enrich-text")
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(body)
                    .retrieve()
                    .body(String.class);

            EnrichmentResult result = parseResponse(link, rawResponse);
            if (result.isAvailable()) {
                log.info("[GenAI] 결과: {} outcome={} sentiment={} summary={}줄 xai={} headline_ko={}",
                        truncate(link), result.getOutcome(), result.getSentimentLabel(),
                        result.getSummary3lines() != null ? result.getSummary3lines().size() : 0,
                        result.getXai() != null ? "있음" : "없음",
                        result.getHeadlineKo() != null ? "있음" : "없음");
            } else {
                log.warn("[GenAI] 분석 실패: {} outcome={}", truncate(link), result.getOutcome());
            }
            return result;
        } catch (Exception e) {
            log.error("[GenAI] enrich-text 오류: {} | {}: {}", truncate(link), e.getClass().getSimpleName(), e.getMessage());
            return EnrichmentResult.unavailable(link);
        }
    }

    /** Python: _parse_direct_response() */
    private EnrichmentResult parseResponse(String sourceUrl, String rawJson) {
        if (rawJson == null || rawJson.isBlank()) return EnrichmentResult.unavailable(sourceUrl);
        try {
            JsonNode root = objectMapper.readTree(rawJson);
            String outcome = root.path("outcome").asText(null);

            // sentiment
            String sentimentLabel = null;
            Double sentimentScore = null;
            JsonNode sentimentNode = root.path("sentiment");
            if (!sentimentNode.isMissingNode() && !sentimentNode.isNull()) {
                sentimentLabel = sentimentNode.path("label").asText(null);
                sentimentScore = sentimentNode.has("score") ? sentimentNode.path("score").asDouble() : null;
            }
            sentimentLabel = normalizeSentiment(sentimentLabel);

            List<String> summary3lines = parseSummaryLines(root.path("summary_3lines"));

            String xai = null;
            if (root.has("xai") && !root.get("xai").isNull()) {
                xai = objectMapper.writeValueAsString(root.get("xai"));
            }

            // localized (Korean) — Python: localized.get("title"), localized.get("summary_3lines"), localized.get("xai")
            String headlineKo = null;
            List<String> summary3linesKo = null;
            String xaiKo = null;
            JsonNode localized = root.path("localized");
            if (!localized.isMissingNode() && !localized.isNull()) {
                headlineKo = localized.path("title").asText(null);
                summary3linesKo = parseSummaryLines(localized.path("summary_3lines"));
                if (localized.has("xai") && !localized.get("xai").isNull()) {
                    xaiKo = objectMapper.writeValueAsString(localized.get("xai"));
                }
            }
            // Python: resolved_summary_ko = summary_3lines_ko or summary_3lines or None
            if (summary3linesKo == null || summary3linesKo.isEmpty()) {
                summary3linesKo = summary3lines;
            }

            return new EnrichmentResult(sourceUrl, sentimentLabel, sentimentScore,
                    summary3lines, xai, headlineKo, summary3linesKo, xaiKo, rawJson, outcome);

        } catch (Exception e) {
            log.warn("[GenAI] 응답 파싱 실패: {} | {}", sourceUrl, e.getMessage());
            return EnrichmentResult.unavailable(sourceUrl);
        }
    }

    private List<String> parseSummaryLines(JsonNode node) {
        if (node == null || node.isMissingNode() || node.isNull()) return null;
        List<String> lines = new ArrayList<>();
        if (node.isArray()) {
            node.forEach(n -> {
                if (n.isTextual()) {
                    lines.add(n.asText());
                } else if (n.isObject()) {
                    String text = n.path("text").asText(null);
                    if (text == null) text = n.path("line").asText(null);
                    if (text == null) text = n.path("content").asText(null);
                    if (text != null) lines.add(text);
                }
            });
        } else if (node.isTextual()) {
            lines.add(node.asText());
        }
        return lines.isEmpty() ? null : lines;
    }

    /** Python: _normalize_sentiment() */
    private String normalizeSentiment(String label) {
        if (label == null) return "neutral";
        return switch (label.toLowerCase()) {
            case "positive", "bullish" -> "positive";
            case "negative", "bearish" -> "negative";
            case "mixed" -> "mixed";
            default -> "neutral";
        };
    }

    private String truncate(String s) {
        return s != null && s.length() > 60 ? s.substring(0, 60) : s;
    }

    @lombok.Getter
    @lombok.AllArgsConstructor
    public static class EnrichmentResult {
        private final String sourceUrl;
        private final String sentimentLabel;
        private final Double sentimentScore;
        private final List<String> summary3lines;
        private final String xai;
        private final String headlineKo;
        private final List<String> summary3linesKo;
        private final String xaiKo;
        private final String rawResponse;
        private final String outcome;

        public static EnrichmentResult unavailable(String sourceUrl) {
            return new EnrichmentResult(sourceUrl, "unavailable", null,
                    null, null, null, null, null, null, "fatal_failure");
        }

        public boolean isAvailable() {
            return !"unavailable".equals(sentimentLabel);
        }

        public boolean isCleanFiltered() {
            return "clean_filtered".equals(outcome);
        }
    }
}
