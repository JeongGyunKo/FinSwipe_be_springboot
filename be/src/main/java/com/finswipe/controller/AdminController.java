package com.finswipe.controller;

import com.finswipe.config.AppProperties;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.client.RestClient;
import org.springframework.web.server.ResponseStatusException;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/admin")
@Slf4j
public class AdminController {

    private final JdbcTemplate jdbc;
    private final AppProperties props;
    private final RestClient genaiClient;
    private final com.finswipe.service.TickerDiscoveryService tickerDiscoveryService;
    private final com.finswipe.service.TickerTimelineService timelineService;

    public AdminController(JdbcTemplate jdbc,
                           AppProperties props,
                           @Qualifier("genaiRestClient") RestClient genaiClient,
                           com.finswipe.service.TickerDiscoveryService tickerDiscoveryService,
                           com.finswipe.service.TickerTimelineService timelineService) {
        this.jdbc = jdbc;
        this.props = props;
        this.genaiClient = genaiClient;
        this.tickerDiscoveryService = tickerDiscoveryService;
        this.timelineService = timelineService;
    }

    /** 전체 유저 목록 — 프리뷰 도구용 */
    @GetMapping("/users")
    public ResponseEntity<List<Map<String, Object>>> users(
            @RequestHeader("X-Admin-Key") String adminKey) {
        requireAdmin(adminKey);
        try {
            List<Map<String, Object>> rows = jdbc.query(
                    """
                    SELECT id, email, display_name, login_id, auth_provider,
                           tickers, level, tendency, news_sort, created_at
                    FROM user_profiles
                    ORDER BY created_at DESC
                    LIMIT 200
                    """,
                    (rs, i) -> {
                        Map<String, Object> m = new LinkedHashMap<>();
                        m.put("userId",       rs.getString("id"));
                        m.put("email",        rs.getString("email"));
                        m.put("displayName",  rs.getString("display_name"));
                        m.put("loginId",      rs.getString("login_id"));
                        m.put("authProvider", rs.getString("auth_provider"));
                        m.put("level",        rs.getObject("level"));
                        m.put("tendency",     rs.getString("tendency"));
                        m.put("newsSort",     rs.getString("news_sort"));
                        String raw = rs.getString("tickers");
                        m.put("tickers", parseTickers(raw));
                        return m;
                    });
            return ResponseEntity.ok(rows);
        } catch (Exception e) {
            log.error("[admin/users] 조회 실패 [{}]: {}", e.getClass().getSimpleName(), e.getMessage(), e);
            throw new org.springframework.web.server.ResponseStatusException(
                    org.springframework.http.HttpStatus.INTERNAL_SERVER_ERROR,
                    e.getClass().getSimpleName() + ": " + e.getMessage());
        }
    }

    /** 특정 유저의 다이제스트 — GenAI 프록시 */
    @PostMapping("/user-digest")
    public ResponseEntity<String> userDigest(
            @RequestHeader("X-Admin-Key") String adminKey,
            @RequestBody Map<String, String> body) {
        requireAdmin(adminKey);
        String userId = body.get("user_id");
        if (userId == null || userId.isBlank()) {
            return ResponseEntity.badRequest()
                    .contentType(MediaType.APPLICATION_JSON)
                    .body("{\"error\":\"user_id 필요\"}");
        }
        try {
            java.util.UUID.fromString(userId);
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest()
                    .contentType(MediaType.APPLICATION_JSON)
                    .body("{\"error\":\"유효하지 않은 userId\"}");
        }
        try {
            return genaiClient.post()
                    .uri("/api/v1/analysis/digest")
                    .contentType(MediaType.APPLICATION_JSON)
                    .body("{\"user_id\":\"" + userId + "\"}")
                    .exchange((req, res) -> {
                        byte[] bytes = res.getBody().readAllBytes();
                        String raw = bytes.length > 0 ? new String(bytes, StandardCharsets.UTF_8) : "{}";
                        return ResponseEntity.status(res.getStatusCode())
                                .contentType(MediaType.APPLICATION_JSON)
                                .body(raw);
                    });
        } catch (Exception e) {
            log.error("[admin/user-digest] 실패: {}", e.getMessage());
            return ResponseEntity.internalServerError()
                    .contentType(MediaType.APPLICATION_JSON)
                    .body("{\"error\":\"분석 서버 오류\"}");
        }
    }

    /** 유저 삭제 — 연관 데이터 포함 */
    @DeleteMapping("/users/{userId}")
    public ResponseEntity<Map<String, Object>> deleteUser(
            @RequestHeader("X-Admin-Key") String adminKey,
            @PathVariable String userId) {
        requireAdmin(adminKey);
        try {
            java.util.UUID.fromString(userId);
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().body(Map.of("error", "유효하지 않은 userId"));
        }
        try {
            int quizQ = jdbc.update(
                "DELETE FROM quiz_questions WHERE session_id IN (SELECT id FROM quiz_sessions WHERE user_id = ?)", userId);
            int quizS = jdbc.update("DELETE FROM quiz_sessions WHERE user_id = ?", userId);
            int reads = jdbc.update("DELETE FROM user_read_articles WHERE user_id = CAST(? AS UUID)", userId);
            int tokens = jdbc.update("DELETE FROM device_tokens WHERE user_id = CAST(? AS UUID)", userId);
            int profile = jdbc.update("DELETE FROM user_profiles WHERE id = CAST(? AS UUID)", userId);
            if (profile == 0) return ResponseEntity.status(HttpStatus.NOT_FOUND).body(Map.of("error", "유저를 찾을 수 없습니다"));
            log.info("[admin] 유저 삭제: userId={} quiz_sessions={} reads={} tokens={}", userId, quizS, reads, tokens);
            return ResponseEntity.ok(Map.of("deleted", true, "quiz_sessions", quizS, "quiz_questions", quizQ, "read_articles", reads));
        } catch (Exception e) {
            log.error("[admin/delete] 실패: {}", e.getMessage(), e);
            throw new ResponseStatusException(HttpStatus.INTERNAL_SERVER_ERROR, e.getMessage());
        }
    }

    /** 유저 프로필 수정 — level / tendency / tickers */
    @PatchMapping("/users/{userId}")
    public ResponseEntity<Map<String, Object>> patchUser(
            @RequestHeader("X-Admin-Key") String adminKey,
            @PathVariable String userId,
            @RequestBody Map<String, Object> body) {
        requireAdmin(adminKey);
        try {
            java.util.UUID.fromString(userId);
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().body(Map.of("error", "유효하지 않은 userId"));
        }
        try {
            if (body.containsKey("level")) {
                Object lvl = body.get("level");
                Integer level = lvl == null ? null : ((Number) lvl).intValue();
                jdbc.update("UPDATE user_profiles SET level = ?, updated_at = NOW() WHERE id = CAST(? AS UUID)", level, userId);
            }
            if (body.containsKey("tendency")) {
                jdbc.update("UPDATE user_profiles SET tendency = ?, updated_at = NOW() WHERE id = CAST(? AS UUID)", body.get("tendency"), userId);
            }
            if (body.containsKey("tickers")) {
                @SuppressWarnings("unchecked")
                java.util.List<String> tickers = (java.util.List<String>) body.get("tickers");
                // 정규화(따옴표/공백 제거·대문자) + CAST 추가 — 기존엔 CAST 누락으로 SQL grammar 오류였음
                java.util.List<String> norm = (tickers == null ? java.util.List.<String>of() : tickers).stream()
                    .map(t -> t.replace("\"", "").strip().toUpperCase())
                    .filter(s -> !s.isEmpty())
                    .distinct()
                    .toList();
                String arr = norm.isEmpty() ? "{}" : "{" + String.join(",", norm) + "}";
                jdbc.update("UPDATE user_profiles SET tickers = CAST(? AS TEXT[]), updated_at = NOW() WHERE id = CAST(? AS UUID)", arr, userId);
            }
            log.info("[admin] 유저 수정: userId={} fields={}", userId, body.keySet());
            return ResponseEntity.ok(Map.of("updated", true));
        } catch (Exception e) {
            log.error("[admin/patch] 실패: {}", e.getMessage(), e);
            throw new ResponseStatusException(HttpStatus.INTERNAL_SERVER_ERROR, e.getMessage());
        }
    }

    private List<String> parseTickers(String raw) {
        if (raw == null || raw.equals("{}") || raw.isBlank()) return List.of();
        String inner = raw.substring(1, raw.length() - 1).trim();
        if (inner.isBlank()) return List.of();
        return List.of(inner.split(","));
    }

    /** BA 카드 BAE Systems 뉴스 정리 — ?confirm=true 시 실제 삭제 */
    @DeleteMapping("/cleanup-bae")
    public ResponseEntity<Map<String, Object>> cleanupBae(
            @RequestHeader("X-Admin-Key") String adminKey,
            @RequestParam(defaultValue = "false") boolean confirm) {
        requireAdmin(adminKey);
        String previewSql = """
                SELECT id, headline, tickers::text
                FROM news_articles
                WHERE 'BA' = ANY(tickers)
                  AND (headline ILIKE '%BAE Systems%' OR content ILIKE '%BAE Systems%')
                LIMIT 100
                """;
        List<Map<String, Object>> targets = jdbc.queryForList(previewSql);
        if (!confirm) {
            return ResponseEntity.ok(Map.of(
                    "preview", targets.stream().map(r -> Map.of(
                            "id", r.get("id"),
                            "headline", r.get("headline"),
                            "tickers", r.get("tickers"))).toList(),
                    "count", targets.size(),
                    "hint", "삭제하려면 ?confirm=true 추가"));
        }
        int deleted = jdbc.update("""
                DELETE FROM news_articles
                WHERE 'BA' = ANY(tickers)
                  AND (headline ILIKE '%BAE Systems%' OR content ILIKE '%BAE Systems%')
                """);
        log.warn("[어드민] BAE Systems 오태깅 기사 {}개 삭제 완료", deleted);
        return ResponseEntity.ok(Map.of("deleted", deleted));
    }

    /** SEC EDGAR Form 25 상장폐지 감지 수동 트리거 */
    @PostMapping("/trigger/delisting-check")
    public ResponseEntity<Map<String, String>> triggerDelistingCheck(
            @RequestHeader("X-Admin-Key") String adminKey) {
        requireAdmin(adminKey);
        Thread.ofVirtual().start(tickerDiscoveryService::syncListingStatus);
        return ResponseEntity.accepted().body(Map.of("status", "started"));
    }

    /** 종목 멀티데이 이벤트 타임라인 — 미국 거래 세션(16:00 ET 마감) 단위. 어드민 프리뷰용. */
    @GetMapping("/ticker-timeline")
    public ResponseEntity<Map<String, Object>> tickerTimeline(
            @RequestHeader("X-Admin-Key") String adminKey,
            @RequestParam String ticker,
            @RequestParam(defaultValue = "5") int sessions) {
        requireAdmin(adminKey);
        try {
            return ResponseEntity.ok(timelineService.getTimeline(ticker, sessions));
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        }
    }

    private void requireAdmin(String key) {
        String expected = props.getAdmin().getApiKey();
        if (!MessageDigest.isEqual(
                key.getBytes(StandardCharsets.UTF_8),
                expected.getBytes(StandardCharsets.UTF_8))) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "Invalid admin key");
        }
    }
}
