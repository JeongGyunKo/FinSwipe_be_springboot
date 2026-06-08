package com.finswipe.controller;

import com.finswipe.config.AppProperties;
import com.finswipe.config.CacheConfig;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.media.Content;
import io.swagger.v3.oas.annotations.media.ExampleObject;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.security.SecurityRequirement;
import io.swagger.v3.oas.annotations.tags.Tag;
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
import org.springframework.security.core.Authentication;
import lombok.extern.slf4j.Slf4j;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

import java.security.MessageDigest;
import java.util.List;
import java.util.Map;
import java.util.Optional;

@Tag(name = "News", description = "뉴스 피드 조회 · 검색 · 읽음 처리 · 푸시 토큰")
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

    @Operation(summary = "뉴스 피드", description = "분석 완료된 기사 목록. sort=time(시간순,기본값) | sort=power(감성강도순). JWT 있으면 읽은 기사 제외 + 관심 티커 필터 적용.")
    @ApiResponse(responseCode = "200", content = @Content(examples = @ExampleObject(value = """
            {
              "total": 1200,
              "offset": 0,
              "data": [
                {
                  "id": "uuid",
                  "headline": "Apple beats earnings estimates",
                  "headlineKo": "애플, 실적 예상치 초과 달성",
                  "summary3linesKo": ["첫 번째 요약", "두 번째 요약", "세 번째 요약"],
                  "sentimentLabel": "positive",
                  "sentimentScore": 7.2,
                  "sentimentReason": "매출 15% 증가와 가이던스 상향이 주요 원인입니다.",
                  "tickers": ["AAPL"],
                  "imageUrl": "https://...",
                  "publishedAt": "2026-06-04T10:00:00Z",
                  "is_read": false
                }
              ],
              "userTickers": ["AAPL", "TSLA"]
            }
            """)))
    @GetMapping("/latest")
    @Cacheable(value = CacheConfig.CACHE_NEWS_LATEST, key = "#sort + ':' + #period + ':' + #limit + ':' + #offset",
               condition = "#auth == null && #userId == null")
    public ResponseEntity<NewsListResponse> getLatest(
            Authentication auth,
            @RequestParam(defaultValue = "20") @Min(1) @Max(100) int limit,
            @RequestParam(defaultValue = "0") @Min(0) int offset,
            @RequestParam(required = false) String userId,
            @RequestParam(defaultValue = "time") String sort,
            @RequestParam(defaultValue = "week") String period,
            @RequestParam(required = false) String ticker) {

        // JWT가 있으면 JWT의 userId를 우선 사용 (파라미터 조작 방지)
        final String resolvedUserId = (auth != null && auth.getPrincipal() instanceof java.util.UUID)
                ? auth.getPrincipal().toString() : userId;

        // ET 장 사이클 계산 — 기본 5일치
        java.time.ZoneId et = java.time.ZoneId.of("America/New_York");
        java.time.ZonedDateTime nowET = java.time.ZonedDateTime.now(et);
        java.time.ZonedDateTime closeToday = nowET.toLocalDate().atTime(16, 0).atZone(et);
        java.time.ZonedDateTime lastClose = nowET.isBefore(closeToday) ? closeToday.minusDays(1) : closeToday;
        int days = "today".equals(period) ? 1 : "all".equals(period) ? 0 : 5;
        final java.time.OffsetDateTime since = (days == 0) ? null
                : lastClose.minusDays(days - 1).toOffsetDateTime();

        if (resolvedUserId != null && isValidUuid(resolvedUserId)) {
            final int pageNum = offset / limit;
            var pageFuture = new java.util.concurrent.CompletableFuture<Page<NewsArticle>>();
            var readFuture = new java.util.concurrent.CompletableFuture<List<NewsArticle>>();
            var tickersFuture = new java.util.concurrent.CompletableFuture<List<String>>();

            final String tickerFilter = (ticker != null && !ticker.isBlank()) ? ticker.strip().toUpperCase() : null;
            Thread.ofVirtual().start(() -> {
                try {
                    java.time.OffsetDateTime effectiveSince = since != null ? since
                            : java.time.OffsetDateTime.now().minusYears(10);
                    Page<NewsArticle> result;
                    if (tickerFilter != null) {
                        result = newsRepo.findUnreadByUserAndTicker(resolvedUserId, effectiveSince, tickerFilter, PageRequest.of(pageNum, limit));
                    } else {
                        List<String> tickers = getUserTickers(resolvedUserId);
                        int tickerCount = Math.max(tickers.size(), 1);
                        int perTicker = Math.max(limit / tickerCount, 10);
                        result = newsRepo.findUnreadByUser(resolvedUserId, effectiveSince, perTicker, PageRequest.of(pageNum, limit));
                    }
                    pageFuture.complete(result);
                }
                catch (Exception e) { pageFuture.completeExceptionally(e); }
            });
            Thread.ofVirtual().start(() -> {
                try { readFuture.complete(newsRepo.findRecentReadArticles(resolvedUserId, 10)); }
                catch (Exception e) { readFuture.completeExceptionally(e); }
            });
            Thread.ofVirtual().start(() -> {
                try { tickersFuture.complete(getUserTickers(resolvedUserId)); }
                catch (Exception e) { tickersFuture.completeExceptionally(e); }
            });

            java.util.concurrent.CompletableFuture.allOf(pageFuture, readFuture, tickersFuture).join();

            Page<NewsArticle> page = pageFuture.join();
            List<NewsArticle> readArticles = readFuture.join();
            List<String> userTickers = tickersFuture.join();

            List<NewsArticleResponse> data = new java.util.ArrayList<>();
            page.getContent().forEach(a ->
                    data.add(new NewsArticleResponse(a, tickerService.enrichTickers(a.getTickers()), false)));
            readArticles.forEach(a ->
                    data.add(new NewsArticleResponse(a, tickerService.enrichTickers(a.getTickers()), true)));
            return ResponseEntity.ok(new NewsListResponse(page.getTotalElements(), offset, data, userTickers));
        }

        org.springframework.data.domain.PageRequest pageReq = PageRequest.of(offset / limit, limit);

        Page<NewsArticle> page = "power".equals(sort)
                ? (since != null ? newsRepo.findTodayOrderByPowerDesc(since, pageReq) : newsRepo.findByXaiKoIsNotNullOrderByPowerDesc(pageReq))
                : (since != null ? newsRepo.findTodayOrderByPublishedAtDesc(since, pageReq) : newsRepo.findByXaiKoIsNotNullOrderByPublishedAtDesc(pageReq));
        List<NewsArticleResponse> data = page.getContent().stream()
                .map(a -> new NewsArticleResponse(a, tickerService.enrichTickers(a.getTickers())))
                .toList();
        return ResponseEntity.ok(new NewsListResponse(page.getTotalElements(), offset, data));
    }

    @Operation(summary = "읽음 처리", description = "스와이프한 기사를 읽음 처리. 이후 피드에서 제외됨.")
    @ApiResponse(responseCode = "200", content = @Content(examples = @ExampleObject(value = """
            { "ok": true }
            """)))
    @SecurityRequirement(name = "bearerAuth")
    @PostMapping("/{articleId}/read")
    public ResponseEntity<Map<String, Boolean>> markAsRead(
            Authentication auth,
            @PathVariable java.util.UUID articleId,
            @RequestParam(required = false) String userId) {
        final String uid = (auth != null && auth.getPrincipal() instanceof java.util.UUID)
                ? auth.getPrincipal().toString() : userId;
        if (uid == null || !isValidUuid(uid)) {
            return ResponseEntity.badRequest().body(Map.of("ok", false));
        }
        try {
            jdbc.update("""
                    INSERT INTO user_read_articles (user_id, article_id)
                    VALUES (CAST(? AS UUID), ?)
                    ON CONFLICT (user_id, article_id) DO NOTHING
                    """, uid, articleId);
            return ResponseEntity.ok(Map.of("ok", true));
        } catch (Exception e) {
            log.error("[읽음] 저장 실패: {}", e.getMessage());
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR).body(Map.of("ok", false));
        }
    }

    @Operation(summary = "뉴스 검색", description = "티커 심볼 또는 회사명으로 검색 (예: AAPL, Apple)")
    @ApiResponse(responseCode = "200", content = @Content(examples = @ExampleObject(value = """
            {
              "count": 50,
              "offset": 0,
              "query": "AAPL",
              "matched_tickers": ["AAPL"],
              "data": [{ "id": "uuid", "headlineKo": "애플 실적 예상치 초과", "sentimentLabel": "positive" }]
            }
            """)))
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
                "count", total,
                "offset", offset,
                "query", q,
                "matched_tickers", matchingTickers,
                "data", data));
    }

    @Operation(summary = "전체 티커 목록", description = "5,500개 미국 주식 티커 + 한국어 회사명. 자동완성에 활용.")
    @ApiResponse(responseCode = "200", content = @Content(examples = @ExampleObject(value = """
            {
              "count": 5543,
              "data": [
                { "ticker": "AAPL", "corp": "Apple Inc.", "ko": "애플" },
                { "ticker": "TSLA", "corp": "Tesla Inc.", "ko": "테슬라" },
                { "ticker": "NVDA", "corp": "NVIDIA Corporation", "ko": "엔비디아" }
              ]
            }
            """)))
    @GetMapping("/tickers")
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

    @Operation(summary = "FCM 토큰 등록", description = "푸시 알림 수신을 위한 FCM 디바이스 토큰 등록. platform: web|ios|android")
    @ApiResponse(responseCode = "200", content = @Content(examples = @ExampleObject(value = """
            { "ok": true }
            """)))
    @SecurityRequirement(name = "bearerAuth")
    @PostMapping("/device-token")
    public ResponseEntity<Map<String, Boolean>> registerDeviceToken(
            Authentication auth,
            @RequestParam(required = false) String userId,
            @Valid @RequestBody DeviceTokenRequest body) {
        final String uid = (auth != null && auth.getPrincipal() instanceof java.util.UUID)
                ? auth.getPrincipal().toString() : userId;
        if (uid == null || !isValidUuid(uid)) {
            return ResponseEntity.badRequest().body(Map.of("ok", false));
        }
        try {
            Integer count = jdbc.queryForObject(
                    "SELECT COUNT(*) FROM device_tokens WHERE user_id = CAST(? AS UUID)",
                    Integer.class, uid);
            if (count != null && count >= 10) {
                return ResponseEntity.status(HttpStatus.TOO_MANY_REQUESTS).body(Map.of("ok", false));
            }
            jdbc.update("""
                    INSERT INTO device_tokens (user_id, token, platform)
                    VALUES (CAST(? AS UUID), ?, ?)
                    ON CONFLICT (user_id, token) DO NOTHING
                    """, uid, body.token(), body.platform());
            return ResponseEntity.ok(Map.of("ok", true));
        } catch (Exception e) {
            log.error("[알림] 토큰 등록 실패: {}", e.getMessage());
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                    .body(Map.of("ok", false));
        }
    }

    @Operation(summary = "FCM 토큰 삭제", description = "로그아웃 또는 알림 해제 시 토큰 제거")
    @ApiResponse(responseCode = "200", content = @Content(examples = @ExampleObject(value = """
            { "ok": true }
            """)))
    @SecurityRequirement(name = "bearerAuth")
    @DeleteMapping("/device-token")
    public ResponseEntity<Map<String, Boolean>> deleteDeviceToken(
            Authentication auth,
            @RequestParam(required = false) String userId,
            @Valid @RequestBody DeviceTokenDeleteRequest body) {
        final String uid = (auth != null && auth.getPrincipal() instanceof java.util.UUID)
                ? auth.getPrincipal().toString() : userId;
        if (uid == null || !isValidUuid(uid)) {
            return ResponseEntity.badRequest().body(Map.of("ok", false));
        }
        try {
            jdbc.update("DELETE FROM device_tokens WHERE user_id = CAST(? AS UUID) AND token = ?",
                    uid, body.token());
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

    private List<String> getUserTickers(String userId) {
        try {
            return jdbc.queryForObject(
                    "SELECT tickers FROM user_profiles WHERE id = CAST(? AS UUID)",
                    (rs, rowNum) -> {
                        String raw = rs.getString("tickers");
                        if (raw == null || raw.equals("{}")) return List.of();
                        raw = raw.substring(1, raw.length() - 1);
                        if (raw.isBlank()) return List.of();
                        return List.of(raw.split(","));
                    }, userId);
        } catch (Exception e) {
            log.warn("[userTickers] 조회 실패: {}", e.getMessage());
            return List.of();
        }
    }

    private static boolean isValidUuid(String value) {
        try { java.util.UUID.fromString(value); return true; }
        catch (IllegalArgumentException e) { return false; }
    }

    private void requireAdmin(String providedKey) {
        String expectedKey = props.getAdmin().getApiKey();
        if (!MessageDigest.isEqual(providedKey.getBytes(java.nio.charset.StandardCharsets.UTF_8), expectedKey.getBytes(java.nio.charset.StandardCharsets.UTF_8))) {
            log.warn("[보안] 유효하지 않은 admin key 시도");
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "Invalid admin key");
        }
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