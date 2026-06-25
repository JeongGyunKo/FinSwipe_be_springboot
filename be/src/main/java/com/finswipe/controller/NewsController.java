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
import com.finswipe.service.TechnicalsService;
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
import java.util.Set;
import java.util.stream.Collectors;

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
    private final TechnicalsService technicalsService;
    private final JobTrackingService jobTracking;
    private final AppProperties props;
    private final JdbcTemplate jdbc;

    // ===================== Public Endpoints =====================

    @Operation(summary = "뉴스 피드", description = "분석 완료된 기사 목록. sort=time(시간순,기본값) | sort=power(감성강도순). JWT 있으면 관심 티커 필터 + 미읽은 기사 우선 적용. 특정 티커에 미읽은 기사가 없으면 최신 공개 기사 5개로 자동 fallback(is_read=true). indicators는 대표 티커의 기술적 지표 4종(RSI·MACD·볼린저밴드·거래량) 배열 — null이면 지표 없이 렌더. currentPrice/changePct1d는 전일 종가 기준, sparkline은 최근 30일 종가 배열.")
    @ApiResponse(responseCode = "200", content = @Content(examples = @ExampleObject(value = """
            {
              "total": 1200,
              "offset": 0,
              "data": [
                {
                  "id": "uuid",
                  "headline": "Apple beats earnings estimates",
                  "headlineKo": "애플, 실적 예상치 초과 달성",
                  "summary3linesKo": ["가이던스 하향이 단기 주가 압력으로 작용할 가능성이 있어요.", "매출 서프라이즈에도 마진 하락이 구조적 우려로 부각될 수 있어요.", "다음 분기 마진 회복 여부가 주가 방향의 핵심 변수가 될 것 같아요."],
                  "sentimentLabel": "positive",
                  "sentimentScore": 72.0,
                  "sentimentReason": "매출 15% 증가와 가이던스 상향이 주요 원인입니다.",
                  "tickers": ["AAPL"],
                  "imageUrl": "https://...",
                  "publishedAt": "2026-06-04T10:00:00Z",
                  "is_read": false,
                  "currentPrice": 211.45,
                  "changePct1d": -1.23,
                  "sparkline": [198.2, 200.1, 203.4, 201.8, 205.3, 207.6, 204.9, 208.1, 206.7, 210.3, 209.5, 212.8, 211.2, 215.4, 213.7, 216.9, 214.3, 218.6, 217.1, 220.4, 219.8, 222.3, 221.5, 218.9, 215.6, 213.2, 209.8, 207.4, 210.1, 211.45],
                  "indicators": [
                    {
                      "type": "RSI",
                      "value": 42.5,
                      "displayText": null,
                      "label": "중립",
                      "caption": "RSI 42.5 — 안정적인 구간이에요."
                    },
                    {
                      "type": "MACD",
                      "value": null,
                      "displayText": "강세",
                      "label": "골든크로스",
                      "caption": "시그널선을 상향 돌파, 상승 모멘텀 강화."
                    },
                    {
                      "type": "볼린저밴드",
                      "value": null,
                      "displayText": "상단",
                      "label": "상단 밴드",
                      "caption": "상단 밴드 근처 — 과열 주의 구간이에요."
                    },
                    {
                      "type": "거래량",
                      "value": 2.3,
                      "displayText": null,
                      "label": "증가",
                      "caption": "평소의 약 2.3배, 거래가 활발해요."
                    }
                  ]
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

        // 보안(IDOR/BOLA 방지): 개인화 userId는 JWT에서만 유도한다.
        // 쿼리 파라미터 userId는 신뢰하지 않으며(비인증 시 무시), 인증이 없으면 개인화 없이 공개 피드를 반환한다.
        final String resolvedUserId = (auth != null && auth.getPrincipal() instanceof java.util.UUID)
                ? auth.getPrincipal().toString() : null;

        // ET 장 사이클 계산 — 기본 1일치 (직전 마감장 16:00 ET 이후 뉴스만, all일 때만 전체)
        java.time.ZoneId et = java.time.ZoneId.of("America/New_York");
        java.time.ZonedDateTime nowET = java.time.ZonedDateTime.now(et);
        java.time.ZonedDateTime closeToday = nowET.toLocalDate().atTime(16, 0).atZone(et);
        java.time.ZonedDateTime lastClose = nowET.isBefore(closeToday) ? closeToday.minusDays(1) : closeToday;
        int days = "all".equals(period) ? 0 : 1;
        final java.time.OffsetDateTime since = (days == 0) ? null
                : lastClose.minusDays(days - 1).toOffsetDateTime();
        // 미읽음·읽음·폴백 모두 동일 윈도우(직전 ET 마감 이후)로 제한. period=all이면 사실상 무제한.
        final java.time.OffsetDateTime effectiveSince = since != null ? since
                : java.time.OffsetDateTime.now().minusYears(10);

        if (resolvedUserId != null && isValidUuid(resolvedUserId)) {
            final int pageNum = offset / limit;
            var pageFuture = new java.util.concurrent.CompletableFuture<Page<NewsArticle>>();
            var readFuture = new java.util.concurrent.CompletableFuture<List<NewsArticle>>();
            var tickersFuture = new java.util.concurrent.CompletableFuture<List<String>>();

            final String tickerFilter = (ticker != null && !ticker.isBlank()) ? ticker.strip().toUpperCase() : null;
            Thread.ofVirtual().start(() -> {
                try {
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
                try { readFuture.complete(newsRepo.findRecentReadArticles(resolvedUserId, effectiveSince, 10)); }
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

            // 안 읽은 기사에서 티커별 커버 여부 확인
            java.util.Set<String> coveredTickers = new java.util.HashSet<>();
            for (NewsArticle a : page.getContent()) {
                if (a.getTickers() != null) coveredTickers.addAll(a.getTickers());
            }

            // 안 읽은 기사가 없는 티커는 최신 공개 기사로 fallback — 단, 조회 기간(since) 내 기사만
            // (since를 무시하면 13일 전 같은 오래된 기사가 유입됨)
            List<NewsArticle> fallbackArticles = new java.util.ArrayList<>();
            if (tickerFilter == null) {
                for (String t : userTickers) {
                    if (!coveredTickers.contains(t)) {
                        try {
                            List<java.util.UUID> ids = newsRepo.findIdsByTickersOverlap(
                                    "{" + t + "}", 5, 0);
                            if (!ids.isEmpty()) {
                                List<NewsArticle> found = newsRepo.findByIdIn(ids);
                                if (since != null) {
                                    found = found.stream()
                                            .filter(a -> a.getPublishedAt() != null && !a.getPublishedAt().isBefore(since))
                                            .toList();
                                }
                                fallbackArticles.addAll(found);
                            }
                        } catch (Exception ignored) {}
                    }
                }
            }

            List<NewsArticle> allArticles = new java.util.ArrayList<>(page.getContent());
            allArticles.addAll(readArticles);
            allArticles.addAll(fallbackArticles);
            Map<String, TechnicalsService.TechnicalsData> technicalsMap = buildTechnicalsMap(allArticles);

            // 중복 제거용 ID 세트
            java.util.Set<java.util.UUID> addedIds = new java.util.HashSet<>();
            List<NewsArticleResponse> data = new java.util.ArrayList<>();
            page.getContent().forEach(a -> {
                if (addedIds.add(a.getId())) {
                    TechnicalsService.TechnicalsData td = technicalsMap.get(repTicker(a));
                    data.add(new NewsArticleResponse(a, tickerService.enrichTickers(a.getTickers()), false,
                            td != null ? td.indicators() : null,
                            price(a, td),
                            td != null ? td.changePct1d() : null,
                            td != null ? td.sparkline() : null));
                }
            });
            readArticles.forEach(a -> {
                if (addedIds.add(a.getId())) {
                    TechnicalsService.TechnicalsData td = technicalsMap.get(repTicker(a));
                    data.add(new NewsArticleResponse(a, tickerService.enrichTickers(a.getTickers()), true,
                            td != null ? td.indicators() : null,
                            price(a, td),
                            td != null ? td.changePct1d() : null,
                            td != null ? td.sparkline() : null));
                }
            });
            fallbackArticles.forEach(a -> {
                if (addedIds.add(a.getId())) {
                    TechnicalsService.TechnicalsData td = technicalsMap.get(repTicker(a));
                    data.add(new NewsArticleResponse(a, tickerService.enrichTickers(a.getTickers()), true,
                            td != null ? td.indicators() : null,
                            price(a, td),
                            td != null ? td.changePct1d() : null,
                            td != null ? td.sparkline() : null));
                }
            });
            return ResponseEntity.ok(new NewsListResponse(page.getTotalElements(), offset, data, userTickers));
        }

        org.springframework.data.domain.PageRequest pageReq = PageRequest.of(offset / limit, limit);

        Page<NewsArticle> page = "power".equals(sort)
                ? (since != null ? newsRepo.findTodayOrderByPowerDesc(since, pageReq) : newsRepo.findByXaiKoIsNotNullOrderByPowerDesc(pageReq))
                : (since != null ? newsRepo.findTodayOrderByPublishedAtDesc(since, pageReq) : newsRepo.findByXaiKoIsNotNullOrderByPublishedAtDesc(pageReq));
        Map<String, TechnicalsService.TechnicalsData> technicalsMap = buildTechnicalsMap(page.getContent());
        List<NewsArticleResponse> data = page.getContent().stream()
                .map(a -> {
                    TechnicalsService.TechnicalsData td = technicalsMap.get(repTicker(a));
                    return new NewsArticleResponse(a, tickerService.enrichTickers(a.getTickers()), false,
                            td != null ? td.indicators() : null,
                            price(a, td),
                            td != null ? td.changePct1d() : null,
                            td != null ? td.sparkline() : null);
                })
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

        // 검색어 앞뒤 따옴표/공백 제거 — FE가 q="NVDA"처럼 따옴표째 보내도 정상 검색되도록 방어
        String cleaned = q.replace("\"", "").strip();
        List<String> matchingTickers = cleaned.isEmpty() ? List.of()
                : tickerService.findMatchingTickerSymbols(cleaned);
        if (matchingTickers.isEmpty()) {
            return ResponseEntity.ok(Map.of("count", 0, "offset", offset, "query", cleaned,
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
                "query", cleaned,
                "matched_tickers", matchingTickers,
                "data", data));
    }

    @Operation(summary = "단일 기사 조회", description = "기사 ID로 단건 조회. 챗 알림·딥링크에서 해당 뉴스로 이동할 때 사용.")
    @SecurityRequirement(name = "bearerAuth")
    @GetMapping("/article/{id}")
    public ResponseEntity<?> getArticle(@PathVariable java.util.UUID id) {
        return newsRepo.findById(id)
                .map(a -> {
                    TechnicalsService.TechnicalsData td = buildTechnicalsMap(List.of(a)).get(repTicker(a));
                    NewsArticleResponse body = new NewsArticleResponse(
                            a, tickerService.enrichTickers(a.getTickers()), false,
                            td != null ? td.indicators() : null,
                            price(a, td),
                            td != null ? td.changePct1d() : null,
                            td != null ? td.sparkline() : null);
                    return ResponseEntity.ok((Object) body);
                })
                .orElseGet(() -> ResponseEntity.status(404).body(Map.of("error", "기사를 찾을 수 없습니다")));
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

    @Operation(summary = "티커 7일 감성 트렌드", description = "최근 7일간 날짜별 감성 통계. 감성 점수 평균 및 positive/negative/neutral 건수 포함.")
    @ApiResponse(responseCode = "200", content = @Content(examples = @ExampleObject(value = """
            {
              "ticker": "AAPL",
              "trend": [
                { "date": "2026-06-03", "articleCount": 5, "avgScore": 4.2, "positive": 3, "negative": 1, "neutral": 1 }
              ]
            }
            """)))
    @GetMapping("/tickers/{ticker}/sentiment-trend")
    public ResponseEntity<Map<String, Object>> getSentimentTrend(
            @PathVariable @Size(min = 1, max = 10) String ticker) {
        String t = ticker.strip().toUpperCase();
        List<Map<String, Object>> rows = jdbc.queryForList("""
                SELECT
                    (DATE_TRUNC('day', published_at AT TIME ZONE 'America/New_York'))::date AS date,
                    COUNT(*)                                                                AS article_count,
                    AVG(sentiment_score)                                                   AS avg_score,
                    COUNT(*) FILTER (WHERE sentiment_label = 'positive')                   AS positive,
                    COUNT(*) FILTER (WHERE sentiment_label = 'negative')                   AS negative,
                    COUNT(*) FILTER (WHERE sentiment_label = 'neutral')                    AS neutral
                FROM news_articles
                WHERE tickers && CAST(ARRAY[?] AS text[])
                  AND sentiment_label IS NOT NULL
                  AND published_at >= NOW() - INTERVAL '7 days'
                GROUP BY 1
                ORDER BY 1 ASC
                """, t);

        List<Map<String, Object>> trend = rows.stream().map(r -> {
            Map<String, Object> entry = new java.util.LinkedHashMap<>();
            entry.put("date", r.get("date") != null ? r.get("date").toString() : null);
            entry.put("articleCount", r.get("article_count"));
            Double avg = r.get("avg_score") instanceof Number n ? n.doubleValue() : null;
            entry.put("avgScore", avg != null ? Math.round(avg * 10000.0) / 100.0 : null);
            entry.put("positive", r.get("positive"));
            entry.put("negative", r.get("negative"));
            entry.put("neutral", r.get("neutral"));
            return entry;
        }).toList();

        return ResponseEntity.ok(Map.of("ticker", t, "trend", trend));
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

    // ===================== Notification Settings =====================

    @Operation(summary = "알림 설정 조회", description = "현재 유저의 알림 설정을 반환합니다.")
    @ApiResponse(responseCode = "200", content = @Content(examples = @ExampleObject(value = """
            { "notify_all_news": true, "notify_sentiment_news": true }
            """)))
    @SecurityRequirement(name = "bearerAuth")
    @GetMapping("/notification-settings")
    public ResponseEntity<Map<String, Object>> getNotificationSettings(Authentication auth) {
        String uid = resolveUserId(auth);
        if (uid == null) return ResponseEntity.status(HttpStatus.UNAUTHORIZED).build();
        try {
            Map<String, Object> settings = jdbc.queryForMap(
                    "SELECT notify_all_news, notify_sentiment_news FROM user_profiles WHERE id = CAST(? AS UUID)",
                    uid);
            return ResponseEntity.ok(settings);
        } catch (Exception e) {
            return ResponseEntity.ok(Map.of("notify_all_news", true, "notify_sentiment_news", true));
        }
    }

    @Operation(summary = "알림 설정 업데이트", description = "모든 알림받기, 감성 알림받기 설정을 변경합니다.")
    @ApiResponse(responseCode = "200", content = @Content(examples = @ExampleObject(value = """
            { "ok": true }
            """)))
    @SecurityRequirement(name = "bearerAuth")
    @PutMapping("/notification-settings")
    public ResponseEntity<Map<String, Boolean>> updateNotificationSettings(
            Authentication auth,
            @RequestBody NotificationSettingsRequest body) {
        String uid = resolveUserId(auth);
        if (uid == null) return ResponseEntity.status(HttpStatus.UNAUTHORIZED).build();
        try {
            jdbc.update("""
                    UPDATE user_profiles
                    SET notify_all_news = ?, notify_sentiment_news = ?
                    WHERE id = CAST(? AS UUID)
                    """, body.notifyAllNews(), body.notifySentimentNews(), uid);
            return ResponseEntity.ok(Map.of("ok", true));
        } catch (Exception e) {
            log.error("[알림설정] 업데이트 실패: {}", e.getMessage());
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR).body(Map.of("ok", false));
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
            log.error("[DB 연결 테스트] 오류", e);
            return ResponseEntity.status(HttpStatus.SERVICE_UNAVAILABLE)
                    .body(Map.of("status", "error", "message", "DB 연결 오류"));
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

    /** POST /news/reset-insights — summary_3lines_ko 초기화 후 전체 재분석 트리거 (비동기) */
    @PostMapping("/reset-insights")
    public ResponseEntity<Map<String, Object>> resetAndReanalyzeInsights(
            @RequestHeader("X-Admin-Key") String adminKey,
            @RequestParam(defaultValue = "200") @Min(1) @Max(2000) int batchSize) {
        requireAdmin(adminKey);

        int reset = jdbc.update("""
                UPDATE news_articles
                SET summary_3lines_ko = NULL,
                    retry_count       = 0
                WHERE content IS NOT NULL
                  AND (sentiment_label IS NULL OR sentiment_label != '_clean_filtered')
                  AND tickers && (
                    SELECT array_agg(DISTINCT t)
                    FROM user_profiles, unnest(tickers) AS t
                    WHERE tickers IS NOT NULL AND array_length(tickers, 1) > 0
                  )
                """);

        String jobId = jobTracking.createJob("reset-insights");
        Thread.ofVirtual().start(() -> {
            jobTracking.startJob(jobId);
            try {
                int total = 0;
                int retries = 0;
                while (retries < 20) {
                    int analyzed = collectorService.reanalyzeUnanalyzed(batchSize);
                    if (analyzed == 0) {
                        retries++;
                        log.info("[인사이트 재분석] 분석기 대기 중 ({}/20)...", retries);
                        Thread.sleep(30_000);
                        continue;
                    }
                    retries = 0;
                    total += analyzed;
                    log.info("[인사이트 재분석] 배치 완료 {}건 (누적 {}건)", analyzed, total);
                    if (analyzed < batchSize) break;
                }
                jobTracking.finishJob(jobId, Map.of("reset", reset, "analyzed", total));
            } catch (Exception e) {
                log.error("[인사이트 재분석] 오류", e);
                jobTracking.failJob(jobId, "재분석 중 오류: " + e.getMessage());
            }
        });

        return ResponseEntity.accepted().body(Map.of(
                "job_id", jobId,
                "reset_count", reset,
                "status", "started"));
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
                log.error("[재분석] 백그라운드 작업 오류", e);
                jobTracking.failJob(jobId, "재분석 작업 중 오류가 발생했습니다.");
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

    private String repTicker(NewsArticle a) {
        List<String> t = a.getTickers();
        return (t != null && !t.isEmpty()) ? t.get(0) : null;
    }

    /** 수집 시 저장된 주가 우선, 없으면 실시간 현재가 사용 */
    private Double price(NewsArticle a, TechnicalsService.TechnicalsData td) {
        if (a.getPriceAtCollection() != null) return a.getPriceAtCollection();
        return td != null ? td.currentPrice() : null;
    }

    private Map<String, TechnicalsService.TechnicalsData> buildTechnicalsMap(List<NewsArticle> articles) {
        Set<String> tickers = articles.stream()
                .map(this::repTicker)
                .filter(t -> t != null)
                .collect(Collectors.toSet());
        if (tickers.isEmpty()) return Map.of();

        java.util.concurrent.ConcurrentHashMap<String, TechnicalsService.TechnicalsData> map =
                new java.util.concurrent.ConcurrentHashMap<>();
        var executor = java.util.concurrent.Executors.newVirtualThreadPerTaskExecutor();
        List<java.util.concurrent.CompletableFuture<Void>> futures = tickers.stream()
                .map(ticker -> java.util.concurrent.CompletableFuture.runAsync(() -> {
                    try {
                        TechnicalsService.TechnicalsData td = technicalsService.getTechnicals(ticker);
                        if (td != null) map.put(ticker, td);
                    } catch (Exception e) {
                        log.warn("[지표] {} 스냅샷 조회 실패: {}", ticker, e.getMessage());
                    }
                }, executor))
                .toList();
        try {
            java.util.concurrent.CompletableFuture.allOf(futures.toArray(new java.util.concurrent.CompletableFuture[0]))
                    .get(10, java.util.concurrent.TimeUnit.SECONDS);
        } catch (java.util.concurrent.TimeoutException e) {
            log.warn("[지표] 기술적 지표 병렬 조회 타임아웃 ({}개 티커) — 부분 결과 반환", tickers.size());
        } catch (Exception e) {
            log.warn("[지표] 기술적 지표 조회 오류: {}", e.getMessage());
        } finally {
            executor.shutdownNow();
        }
        return map;
    }

    private List<String> getUserTickers(String userId) {
        try {
            return jdbc.queryForObject(
                    "SELECT tickers FROM user_profiles WHERE id = CAST(? AS UUID)",
                    (rs, rowNum) -> {
                        String raw = rs.getString("tickers");
                        if (raw == null || raw.equals("{}")) return List.of();
                        raw = raw.substring(1, raw.length() - 1);
                        if (raw.isBlank()) return List.of();
                        // Postgres 배열 따옴표/공백 제거 — 저장값에 따옴표가 섞여도 깨끗한 심볼 반환
                        return java.util.Arrays.stream(raw.split(","))
                                .map(s -> s.replace("\"", "").strip())
                                .filter(s -> !s.isEmpty())
                                .toList();
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

    record NotificationSettingsRequest(
            @com.fasterxml.jackson.annotation.JsonProperty("notify_all_news") boolean notifyAllNews,
            @com.fasterxml.jackson.annotation.JsonProperty("notify_sentiment_news") boolean notifySentimentNews) {}

    private String resolveUserId(Authentication auth) {
        if (auth != null && auth.getPrincipal() instanceof java.util.UUID) {
            return auth.getPrincipal().toString();
        }
        return null;
    }
}