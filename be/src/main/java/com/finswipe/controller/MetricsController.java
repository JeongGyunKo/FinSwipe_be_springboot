package com.finswipe.controller;

import com.finswipe.config.AppProperties;
import com.finswipe.service.AnalyzerService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.cache.CacheManager;
import org.springframework.cache.caffeine.CaffeineCache;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.security.MessageDigest;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;

@Tag(name = "Metrics", description = "KPI · 시스템 메트릭 · 로그 모니터링 (어드민 전용)")
@RestController
@RequestMapping("/admin/metrics")
@RequiredArgsConstructor
@Slf4j
public class MetricsController {

    private final JdbcTemplate jdbc;
    private final CacheManager cacheManager;
    private final AppProperties props;
    private final AnalyzerService analyzerService;

    @Operation(summary = "KPI 대시보드", description = "기사 현황, 분석 성능, 비용 추정, 캐시 상태")
    @GetMapping
    public ResponseEntity<Map<String, Object>> metrics(
            @RequestHeader("X-Admin-Key") String adminKey) {
        requireAdmin(adminKey);

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("timestamp", Instant.now().toString());

        // ── 기사 현황 ──────────────────────────────────────────────────
        try {
            Map<String, Object> articles = new LinkedHashMap<>();
            articles.put("total", jdbc.queryForObject("SELECT COUNT(*) FROM news_articles", Long.class));
            articles.put("analyzed", jdbc.queryForObject(
                    "SELECT COUNT(*) FROM news_articles WHERE sentiment_reason IS NOT NULL", Long.class));
            articles.put("pending", jdbc.queryForObject(
                    "SELECT COUNT(*) FROM news_articles WHERE content IS NOT NULL AND sentiment_reason IS NULL AND (sentiment_label IS NULL OR sentiment_label != '_clean_filtered') AND retry_count < 3", Long.class));
            articles.put("filtered", jdbc.queryForObject(
                    "SELECT COUNT(*) FROM news_articles WHERE sentiment_label = '_clean_filtered'", Long.class));
            articles.put("today", jdbc.queryForObject(
                    "SELECT COUNT(*) FROM news_articles WHERE created_at > NOW() - INTERVAL '24 hours'", Long.class));
            result.put("articles", articles);
        } catch (Exception e) {
            log.error("[metrics] articles 조회 오류", e);
            result.put("articles", Map.of("error", "조회 오류"));
        }

        // ── 분석 성능 ──────────────────────────────────────────────────
        try {
            Map<String, Object> analysis = new LinkedHashMap<>();
            long analyzed = (Long) ((Map<?, ?>) result.get("articles")).get("analyzed");
            long total = (Long) ((Map<?, ?>) result.get("articles")).get("total");
            analysis.put("completion_rate_pct", total > 0 ? Math.round(analyzed * 100.0 / total) : 0);
            analysis.put("genai_status", analyzerService.checkHealth().get("status"));

            // 최근 1시간 분석 속도
            Long recentAnalyzed = jdbc.queryForObject(
                    "SELECT COUNT(*) FROM news_articles WHERE sentiment_reason IS NOT NULL AND updated_at > NOW() - INTERVAL '1 hour'",
                    Long.class);
            analysis.put("analyzed_last_1h", recentAnalyzed);
            result.put("analysis", analysis);
        } catch (Exception e) {
            log.error("[metrics] analysis 조회 오류", e);
            result.put("analysis", Map.of("error", "조회 오류"));
        }

        // ── Gemini 비용 추정 ───────────────────────────────────────────
        try {
            long analyzed = (Long) ((Map<?, ?>) result.get("articles")).get("analyzed");
            double costPerArticle = 0.00039;  // ~3회 Gemini 호출 × $0.00013
            Map<String, Object> cost = new LinkedHashMap<>();
            cost.put("model", "gemini-2.5-flash-lite");
            cost.put("cost_per_article_usd", costPerArticle);
            cost.put("total_estimated_usd", Math.round(analyzed * costPerArticle * 100.0) / 100.0);
            cost.put("monthly_at_100_articles_per_day_usd", Math.round(100 * 30 * costPerArticle * 100.0) / 100.0);
            result.put("gemini_cost_estimate", cost);
        } catch (Exception e) {
            log.error("[metrics] gemini_cost 계산 오류", e);
            result.put("gemini_cost_estimate", Map.of("error", "계산 오류"));
        }

        // ── 캐시 통계 ──────────────────────────────────────────────────
        Map<String, Object> caches = new LinkedHashMap<>();
        for (String name : new String[]{"newsLatest", "newsSearch", "tickers"}) {
            try {
                var cache = cacheManager.getCache(name);
                if (cache instanceof CaffeineCache cc) {
                    var stats = cc.getNativeCache().stats();
                    caches.put(name, Map.of(
                            "size", cc.getNativeCache().estimatedSize(),
                            "hit_rate_pct", Math.round(stats.hitRate() * 100),
                            "eviction_count", stats.evictionCount()
                    ));
                }
            } catch (Exception ignored) {}
        }
        result.put("cache", caches);

        // ── 사용자 현황 ────────────────────────────────────────────────
        try {
            Map<String, Object> users = new LinkedHashMap<>();
            users.put("total", jdbc.queryForObject("SELECT COUNT(*) FROM user_profiles", Long.class));
            users.put("with_tickers", jdbc.queryForObject(
                    "SELECT COUNT(*) FROM user_profiles WHERE tickers IS NOT NULL AND array_length(tickers, 1) > 0", Long.class));
            users.put("with_level", jdbc.queryForObject(
                    "SELECT COUNT(*) FROM user_profiles WHERE level IS NOT NULL", Long.class));
            result.put("users", users);
        } catch (Exception e) {
            log.error("[metrics] users 조회 오류", e);
            result.put("users", Map.of("error", "조회 오류"));
        }

        // ── 퀴즈 현황 ──────────────────────────────────────────────────
        try {
            Map<String, Object> quiz = new LinkedHashMap<>();
            quiz.put("total_sessions", jdbc.queryForObject("SELECT COUNT(*) FROM quiz_sessions", Long.class));
            quiz.put("completed", jdbc.queryForObject(
                    "SELECT COUNT(*) FROM quiz_sessions WHERE status = 'completed'", Long.class));
            quiz.put("deep_analysis", jdbc.queryForObject(
                    "SELECT COUNT(*) FROM quiz_sessions WHERE analysis_depth = 'deep'", Long.class));
            result.put("quiz", quiz);
        } catch (Exception e) {
            log.error("[metrics] quiz 조회 오류", e);
            result.put("quiz", Map.of("error", "조회 오류"));
        }

        return ResponseEntity.ok(result);
    }

    private void requireAdmin(String key) {
        String expected = props.getAdmin().getApiKey();
        if (!MessageDigest.isEqual(key.getBytes(java.nio.charset.StandardCharsets.UTF_8), expected.getBytes(java.nio.charset.StandardCharsets.UTF_8))) {
            throw new org.springframework.web.server.ResponseStatusException(
                    org.springframework.http.HttpStatus.FORBIDDEN, "Invalid admin key");
        }
    }
}
