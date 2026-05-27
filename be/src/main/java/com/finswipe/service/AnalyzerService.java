package com.finswipe.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.finswipe.config.AppProperties;
import com.finswipe.domain.entity.NewsArticle;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientResponseException;

import java.nio.charset.StandardCharsets;
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
    private final RestClient genaiHealthClient;
    private final ExecutorService enrichmentExecutor;
    private final ObjectMapper objectMapper;
    private final Semaphore submitSemaphore;

    public AnalyzerService(@Qualifier("genaiRestClient") RestClient genaiClient,
                           @Qualifier("genaiHealthRestClient") RestClient genaiHealthClient,
                           @Qualifier("enrichmentExecutor") ExecutorService enrichmentExecutor,
                           ObjectMapper objectMapper,
                           AppProperties props) {
        this.genaiClient = genaiClient;
        this.genaiHealthClient = genaiHealthClient;
        this.enrichmentExecutor = enrichmentExecutor;
        this.objectMapper = objectMapper;
        this.submitSemaphore = new Semaphore(props.getGenai().getConcurrentRequests());
    }

    /** Python: check_genai_health() — 30초 전용 클라이언트로 빠른 상태 확인 */
    public Map<String, String> checkHealth() {
        try {
            genaiHealthClient.get().uri("/health").retrieve().toBodilessEntity();
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

        // 배치 시작 전 서버 상태 확인 (30초 타임아웃) — 다운 시 기사당 300초 대기 낭비 방지
        Map<String, String> health = checkHealth();
        if (!"ok".equals(health.get("status"))) {
            log.warn("[GenAI] 서버 비정상 ({}) → 배치 전체 스킵 ({}개)", health, valid.size());
            return valid.stream().map(a -> EnrichmentResult.unavailable(a.getSourceUrl())).toList();
        }

        List<CompletableFuture<EnrichmentResult>> futures = valid.stream()
                .map(article -> CompletableFuture.supplyAsync(() -> {
                    try {
                        submitSemaphore.acquire();
                        try {
                            Thread.sleep(1000);
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

    /** 분석 완료 즉시 콜백 호출 — 저장을 기다리지 않고 실시간 처리 */
    public void analyzeBatchStreaming(List<NewsArticle> articles,
                                     java.util.function.BiConsumer<NewsArticle, EnrichmentResult> onEach) {
        List<NewsArticle> valid = articles.stream()
                .filter(a -> a.getSourceUrl() != null && !a.getSourceUrl().isBlank()
                        && a.getContent() != null && !a.getContent().isBlank())
                .toList();

        log.info("[GenAI] enrichment 시작 → {}개", valid.size());

        Map<String, String> health = checkHealth();
        if (!"ok".equals(health.get("status"))) {
            log.warn("[GenAI] 서버 비정상 ({}) → 배치 전체 스킵 ({}개)", health, valid.size());
            valid.forEach(a -> onEach.accept(a, EnrichmentResult.unavailable(a.getSourceUrl())));
            return;
        }

        List<CompletableFuture<Void>> futures = valid.stream()
                .map(article -> CompletableFuture.supplyAsync(() -> {
                    try {
                        submitSemaphore.acquire();
                        try {
                            Thread.sleep(1000);
                            return enrichSingle(article);
                        } finally {
                            submitSemaphore.release();
                        }
                    } catch (InterruptedException e) {
                        Thread.currentThread().interrupt();
                        return EnrichmentResult.unavailable(article.getSourceUrl());
                    }
                }, enrichmentExecutor).thenAccept(result -> onEach.accept(article, result)))
                .toList();

        CompletableFuture.allOf(futures.toArray(new CompletableFuture[0])).join();
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

        // 재분석(headline_ko 등 누락)은 캐시 우회, 신규는 하루 캐시
        boolean isRetry = article.getSentimentLabel() != null;
        String cacheBuster = isRetry
                ? "?t=" + System.currentTimeMillis()
                : "?d=" + LocalDate.now();
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
            // .exchange()로 메시지 컨버터를 우회해 Content-Type 무관하게 바디를 직접 읽음
            String rawResponse = genaiClient.post()
                    .uri("/api/v1/articles/enrich-text")
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(body)
                    .exchange((req, res) -> {
                        byte[] bytes = res.getBody().readAllBytes();
                        return bytes.length > 0 ? new String(bytes, StandardCharsets.UTF_8) : null;
                    });

            EnrichmentResult result = parseResponse(link, rawResponse);
            if (result.isAnalyzed()) {
                log.info("[GenAI] 결과: {} outcome={} sentiment={} summary={}줄 xai={} headline_ko={}",
                        truncate(link), result.getOutcome(), result.getSentimentLabel(),
                        result.getSummary3lines() != null ? result.getSummary3lines().size() : 0,
                        result.getXai() != null ? "있음" : "없음",
                        result.getHeadlineKo() != null ? "있음" : "없음");
            } else {
                log.warn("[GenAI] 빈 응답 (분석 미완료): {} | raw={}", truncate(link),
                        rawResponse != null && rawResponse.length() > 200
                                ? rawResponse.substring(0, 200) + "…"
                                : rawResponse);
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

            // 서버 오류 응답 {"detail": "..."} — 타임아웃/큐 대기 등 → 재시도 대상
            if (root.has("detail") && !root.has("outcome") && !root.has("sentiment")) {
                log.warn("[GenAI] 서버 오류 → 재시도 대기: {} | {}", truncate(sourceUrl),
                        root.path("detail").asText());
                return EnrichmentResult.unavailable(sourceUrl);
            }

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

        /** GenAI 서버와 통신 자체가 성공했는지 (빈 응답 포함) */
        public boolean isAvailable() {
            return !"unavailable".equals(sentimentLabel);
        }

        /** 실제 분석 결과가 있는지 — headline_ko 또는 summary가 존재해야 진짜 분석 완료 */
        public boolean isAnalyzed() {
            return isAvailable() && (headlineKo != null || (summary3lines != null && !summary3lines.isEmpty()));
        }

        public boolean isCleanFiltered() {
            return "clean_filtered".equals(outcome);
        }
    }
}
