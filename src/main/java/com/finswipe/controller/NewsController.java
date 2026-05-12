package com.finswipe.controller;

import com.finswipe.config.AppProperties;
import com.finswipe.config.CacheConfig;
import com.finswipe.domain.entity.NewsArticle;
import com.finswipe.domain.repository.NewsArticleRepository;
import com.finswipe.dto.request.AnalyzeRequest;
import com.finswipe.dto.request.DiagnoseRequest;
import com.finswipe.dto.response.*;
import com.finswipe.job.JobInfo;
import com.finswipe.job.JobTrackingService;
import com.finswipe.service.AnalyzerService;
import com.finswipe.service.NewsCollectorService;
import com.finswipe.service.TickerService;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;

import java.security.MessageDigest;
import java.util.List;
import java.util.Map;
import java.util.Optional;

@RestController
@RequestMapping("/news")
@RequiredArgsConstructor
@Slf4j
public class NewsController {

    private final NewsArticleRepository newsRepo;
    private final TickerService tickerService;
    private final AnalyzerService analyzerService;
    private final NewsCollectorService collectorService;
    private final JobTrackingService jobTracking;
    private final AppProperties props;
    private final JdbcTemplate jdbc;

    // ===================== Public Endpoints =====================

    /** GET /news/latest — 최신 뉴스 목록 (페이징). userId 전달 시 읽은 기사 제외 */
    @GetMapping("/latest")
    @Cacheable(value = CacheConfig.CACHE_NEWS_LATEST, key = "#limit + ':' + #offset",
               condition = "#userId == null")
    public ResponseEntity<NewsListResponse> getLatest(
            @RequestParam(defaultValue = "20") @Min(1) @Max(100) int limit,
            @RequestParam(defaultValue = "0") @Min(0) int offset,
            @RequestParam(required = false) String userId) {

        if (userId != null && isValidUuid(userId)) {
            List<NewsArticle> articles = newsRepo.findUnreadByUser(userId, limit, offset);
            long total = newsRepo.countUnreadByUser(userId);
            List<NewsArticleResponse> data = articles.stream()
                    .map(a -> new NewsArticleResponse(a, tickerService.enrichTickers(a.getTickers())))
                    .toList();
            return ResponseEntity.ok(new NewsListResponse(total, offset, data));
        }

        Page<NewsArticle> page = newsRepo.findByXaiKoIsNotNullOrderByPublishedAtDesc(
                PageRequest.of(offset / limit, limit));
        List<NewsArticleResponse> data = page.getContent().stream()
                .map(a -> new NewsArticleResponse(a, tickerService.enrichTickers(a.getTickers())))
                .toList();
        return ResponseEntity.ok(new NewsListResponse(page.getTotalElements(), offset, data));
    }

    /** POST /news/{articleId}/read — 기사 읽음 처리 */
    @PostMapping("/{articleId}/read")
    public ResponseEntity<Map<String, Boolean>> markAsRead(
            @PathVariable java.util.UUID articleId,
            @RequestParam String userId) {
        if (!isValidUuid(userId)) {
            return ResponseEntity.badRequest().body(Map.of("ok", false));
        }
        try {
            jdbc.update("""
                    INSERT INTO user_read_articles (user_id, article_id)
                    VALUES (?::uuid, ?)
                    ON CONFLICT (user_id, article_id) DO NOTHING
                    """, userId, articleId);
            return ResponseEntity.ok(Map.of("ok", true));
        } catch (Exception e) {
            log.error("[읽음] 저장 실패: {}", e.getMessage());
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR).body(Map.of("ok", false));
        }
    }

    /** GET /news/search?q= — 티커/회사명으로 뉴스 검색 */
    @GetMapping("/search")
    @Cacheable(value = CacheConfig.CACHE_NEWS_SEARCH, key = "#q.toLowerCase() + ':' + #limit + ':' + #offset")
    public ResponseEntity<Map<String, Object>> search(
            @RequestParam @Size(min = 1, max = 100) String q,
            @RequestParam(defaultValue = "20") @Min(1) @Max(100) int limit,
            @RequestParam(defaultValue = "0") @Min(0) int offset) {

        List<String> matchingTickers = tickerService.findMatchingTickerSymbols(q);
        if (matchingTickers.isEmpty()) {
            return ResponseEntity.ok(Map.of("count", 0, "offset", offset, "query", q,
                    "matched_tickers", List.of(), "data", List.of()));
        }

        String tickersArray = "{" + String.join(",", matchingTickers) + "}";
        long total = newsRepo.countByTickersOverlap(tickersArray);
        List<java.util.UUID> ids = newsRepo.findIdsByTickersOverlap(tickersArray, limit, offset);
        List<NewsArticle> articles = ids.isEmpty() ? List.of() : newsRepo.findByIdIn(ids);

        List<NewsArticleResponse> data = articles.stream()
                .map(a -> new NewsArticleResponse(a, tickerService.enrichTickers(a.getTickers())))
                .toList();

        return ResponseEntity.ok(Map.of(
                "count", (int) total,
                "offset", offset,
                "query", q,
                "matched_tickers", matchingTickers,
                "data", data));
    }

    /** GET /news/tickers — 전체 티커 목록 (자동완성용) */
    @GetMapping("/tickers")
    @Cacheable(CacheConfig.CACHE_TICKERS)
    public ResponseEntity<Map<String, Object>> getTickers() {
        List<TickerInfo> tickers = tickerService.getAllTickers();
        return ResponseEntity.ok(Map.of("count", tickers.size(), "data", tickers));
    }

    /** GET /news/genai/health — GenAI 서버 상태 */
    @GetMapping("/genai/health")
    public ResponseEntity<Map<String, String>> getGenAiHealth() {
        return ResponseEntity.ok(analyzerService.checkHealth());
    }

    // ===================== Device Token Endpoints =====================

    /** POST /news/device-token — 디바이스 푸시 알림 토큰 등록 */
    @PostMapping("/device-token")
    public ResponseEntity<Map<String, Boolean>> registerDeviceToken(
            @RequestParam String userId,
            @Valid @RequestBody DeviceTokenRequest body) {
        if (!isValidUuid(userId)) {
            log.warn("[알림] 유효하지 않은 userId: {}", userId);
            return ResponseEntity.badRequest().body(Map.of("ok", false));
        }
        try {
            // 사용자당 최대 10개 토큰 제한 (기기 무제한 등록 방지)
            Integer count = jdbc.queryForObject(
                    "SELECT COUNT(*) FROM device_tokens WHERE user_id = ?::uuid",
                    Integer.class, userId);
            if (count != null && count >= 10) {
                log.warn("[알림] 토큰 한도 초과: userId={}", userId);
                return ResponseEntity.status(HttpStatus.TOO_MANY_REQUESTS).body(Map.of("ok", false));
            }
            jdbc.update("""
                    INSERT INTO device_tokens (user_id, token, platform)
                    VALUES (?::uuid, ?, ?)
                    ON CONFLICT (user_id, token) DO NOTHING
                    """, userId, body.token(), body.platform());
            return ResponseEntity.ok(Map.of("ok", true));
        } catch (Exception e) {
            log.error("[알림] 토큰 등록 실패: {}", e.getMessage());
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                    .body(Map.of("ok", false));
        }
    }

    /** DELETE /news/device-token — 디바이스 푸시 알림 토큰 삭제 */
    @DeleteMapping("/device-token")
    public ResponseEntity<Map<String, Boolean>> deleteDeviceToken(
            @RequestParam String userId,
            @Valid @RequestBody DeviceTokenDeleteRequest body) {
        if (!isValidUuid(userId)) {
            return ResponseEntity.badRequest().body(Map.of("ok", false));
        }
        try {
            jdbc.update("DELETE FROM device_tokens WHERE user_id = ?::uuid AND token = ?",
                    userId, body.token());
            return ResponseEntity.ok(Map.of("ok", true));
        } catch (Exception e) {
            log.error("[알림] 토큰 삭제 실패: {}", e.getMessage());
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                    .body(Map.of("ok", false));
        }
    }

    // ===================== Admin Endpoints =====================

    /** GET /news/test — DB 연결 테스트 (Python: GET) */
    @GetMapping("/test")
    public ResponseEntity<Map<String, Object>> testConnection(
            @RequestHeader("X-Admin-Key") String adminKey) {
        requireAdmin(adminKey);
        try {
            long count = newsRepo.count();
            return ResponseEntity.ok(Map.of("status", "ok", "article_count", count));
        } catch (Exception e) {
            return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE)
                    .body(Map.of("status", "error", "message", e.getMessage()));
        }
    }

    /** POST /news/collect — 수동 뉴스 수집 트리거 */
    @PostMapping("/collect")
    public ResponseEntity<Map<String, Object>> triggerCollect(
            @RequestHeader("X-Admin-Key") String adminKey) {
        requireAdmin(adminKey);
        Map<String, Object> result = collectorService.collectMarketNews();
        return ResponseEntity.ok(result);
    }

    /** POST /news/reanalyze — 미분석 기사 재분석 (비동기) */
    @PostMapping("/reanalyze")
    public ResponseEntity<Map<String, String>> triggerReanalyze(
            @RequestHeader("X-Admin-Key") String adminKey,
            @RequestParam(defaultValue = "50") @Min(1) @Max(200) int limit) {
        requireAdmin(adminKey);
        String jobId = jobTracking.createJob("reanalyze");

        Thread.ofVirtual().start(() -> {
            jobTracking.startJob(jobId);
            try {
                int count = collectorService.reanalyzeUnanalyzed(limit);
                jobTracking.finishJob(jobId, Map.of("analyzed", count));
            } catch (Exception e) {
                jobTracking.failJob(jobId, e.getMessage());
            }
        });

        return ResponseEntity.accepted().body(Map.of("job_id", jobId, "status", "pending"));
    }

    /** GET /news/jobs/{jobId} — 백그라운드 작업 상태 조회 */
    @GetMapping("/jobs/{jobId}")
    public ResponseEntity<JobStatusResponse> getJobStatus(
            @RequestHeader("X-Admin-Key") String adminKey,
            @PathVariable String jobId) {
        requireAdmin(adminKey);

        Optional<JobInfo> job = jobTracking.getJob(jobId);
        if (job.isEmpty()) return ResponseEntity.notFound().build();

        JobInfo j = job.get();
        return ResponseEntity.ok(new JobStatusResponse(
                j.getJobId(), j.getName(), j.getStatus().name().toLowerCase(),
                j.getCreatedAt().toString(),
                j.getStartedAt() != null ? j.getStartedAt().toString() : null,
                j.getFinishedAt() != null ? j.getFinishedAt().toString() : null,
                j.getResult(), j.getError()));
    }

    /** POST /news/analyze — 단일 기사 분석 */
    @PostMapping("/analyze")
    public ResponseEntity<Map<String, Object>> analyzeArticle(
            @RequestHeader("X-Admin-Key") String adminKey,
            @Valid @RequestBody AnalyzeRequest req) {
        requireAdmin(adminKey);

        NewsArticle article = new NewsArticle();
        article.setHeadline(req.getHeadline());
        article.setSourceUrl(req.getSourceUrl());
        article.setContent(req.getContent());
        article.setTickers(req.getTickers());

        AnalyzerService.EnrichmentResult result = analyzerService.enrichSingle(article);
        return ResponseEntity.ok(Map.of(
                "status", result.isAvailable() ? "ok" : "unavailable",
                "sentiment_label", String.valueOf(result.getSentimentLabel()),
                "sentiment_score", String.valueOf(result.getSentimentScore()),
                "summary_3lines", result.getSummary3lines() != null ? result.getSummary3lines() : List.of(),
                "headline_ko", String.valueOf(result.getHeadlineKo())));
    }

    /** GET /news/analyze/latest — 최신 기사 배치 분석 */
    @GetMapping("/analyze/latest")
    public ResponseEntity<Map<String, Object>> analyzeLatest(
            @RequestHeader("X-Admin-Key") String adminKey,
            @RequestParam(defaultValue = "10") @Min(1) @Max(50) int limit) {
        requireAdmin(adminKey);
        int count = collectorService.reanalyzeUnanalyzed(limit);
        return ResponseEntity.ok(Map.of("status", "ok", "analyzed", count));
    }

    /** POST /news/diagnose — 기사 분석 진단 (raw GenAI 응답) */
    @PostMapping("/diagnose")
    public ResponseEntity<Map<String, Object>> diagnose(
            @RequestHeader("X-Admin-Key") String adminKey,
            @Valid @RequestBody DiagnoseRequest req) {
        requireAdmin(adminKey);

        String url = req.getSourceUrl().replaceAll("/$", "");
        Optional<NewsArticle> article = newsRepo.findBySourceUrl(url)
                .or(() -> newsRepo.findBySourceUrl(url + "/"));
        if (article.isEmpty()) {
            return ResponseEntity.status(HttpStatus.NOT_FOUND)
                    .body(Map.of("error", "기사를 찾을 수 없습니다"));
        }

        AnalyzerService.EnrichmentResult result = analyzerService.enrichSingle(article.get());
        return ResponseEntity.ok(Map.of(
                "submitted", true,
                "raw_response", String.valueOf(result.getRawResponse()),
                "article_info", Map.of(
                        "url", url,
                        "title", article.get().getHeadline() != null ? article.get().getHeadline() : "",
                        "content_length", article.get().getContent() != null ? article.get().getContent().length() : 0)));
    }

    // ===================== 내부 유틸 =====================

    private static boolean isValidUuid(String value) {
        try { java.util.UUID.fromString(value); return true; }
        catch (IllegalArgumentException e) { return false; }
    }

    private void requireAdmin(String providedKey) {
        String expectedKey = props.getAdmin().getApiKey();
        if (!MessageDigest.isEqual(providedKey.getBytes(), expectedKey.getBytes())) {
            log.warn("[보안] 유효하지 않은 admin key 시도");
            throw new AdminKeyException("Invalid admin key");
        }
    }

    @ResponseStatus(HttpStatus.FORBIDDEN)
    static class AdminKeyException extends RuntimeException {
        AdminKeyException(String message) { super(message); }
    }

    // ===================== Request Body Records =====================

    record DeviceTokenRequest(
            @NotBlank @Size(min = 10, max = 500) String token,
            @Pattern(regexp = "^(web|ios|android)$") String platform) {
        DeviceTokenRequest { if (platform == null) platform = "web"; }
    }

    record DeviceTokenDeleteRequest(
            @NotBlank @Size(min = 10, max = 500) String token) {}
}