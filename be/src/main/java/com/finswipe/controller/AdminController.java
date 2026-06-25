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

    public AdminController(JdbcTemplate jdbc,
                           AppProperties props,
                           @Qualifier("genaiRestClient") RestClient genaiClient,
                           com.finswipe.service.TickerDiscoveryService tickerDiscoveryService) {
        this.jdbc = jdbc;
        this.props = props;
        this.genaiClient = genaiClient;
        this.tickerDiscoveryService = tickerDiscoveryService;
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

    // ── 미국 거래 세션(16:00 ET 마감) 계산 ──────────────────────────────
    private static final java.time.ZoneId MARKET_ZONE = java.time.ZoneId.of("America/New_York");
    private static final java.time.LocalTime MARKET_CLOSE = java.time.LocalTime.of(16, 0);
    // 미국 증시 정기 휴장일은 규칙으로 계산(연도별 캐시) — 매년 수동 갱신 불필요.
    private static final java.util.Map<Integer, java.util.Set<java.time.LocalDate>> HOLIDAY_CACHE =
            new java.util.concurrent.ConcurrentHashMap<>();
    // 예고 없는 임시 휴장(대통령 국장일, 9/11·허리케인 등 비정기) — 발표되면 여기에만 추가.
    private static final java.util.Set<java.time.LocalDate> AD_HOC_CLOSURES = java.util.Set.of(
            java.time.LocalDate.of(2025, 1, 9));   // 카터 전 대통령 국장

    /** 토·일·정기휴장·임시휴장 여부. 연도 무관 자동 계산. */
    private static boolean marketClosed(java.time.LocalDate d) {
        java.time.DayOfWeek w = d.getDayOfWeek();
        if (w == java.time.DayOfWeek.SATURDAY || w == java.time.DayOfWeek.SUNDAY) return true;
        if (AD_HOC_CLOSURES.contains(d)) return true;
        return HOLIDAY_CACHE.computeIfAbsent(d.getYear(), AdminController::usMarketHolidays).contains(d);
    }

    /** 해당 연도 미국 증시 정기 휴장일 10종 계산(고정일·N번째 요일·Good Friday). */
    private static java.util.Set<java.time.LocalDate> usMarketHolidays(int year) {
        java.util.Set<java.time.LocalDate> h = new java.util.HashSet<>();
        java.util.function.UnaryOperator<java.time.LocalDate> obs = d -> switch (d.getDayOfWeek()) {
            case SATURDAY -> d.minusDays(1);   // 토 → 전날 금
            case SUNDAY   -> d.plusDays(1);    // 일 → 다음 월
            default       -> d;
        };
        // 고정일(주말 대체 관측 적용)
        h.add(obs.apply(java.time.LocalDate.of(year, 1, 1)));     // 신정
        if (year >= 2022) h.add(obs.apply(java.time.LocalDate.of(year, 6, 19)));  // 준틴스(2022~)
        h.add(obs.apply(java.time.LocalDate.of(year, 7, 4)));     // 독립기념일
        h.add(obs.apply(java.time.LocalDate.of(year, 12, 25)));   // 크리스마스
        // N번째 요일
        var w = java.time.temporal.TemporalAdjusters.dayOfWeekInMonth(3, java.time.DayOfWeek.MONDAY);
        h.add(java.time.LocalDate.of(year, 1, 1).with(w));   // MLK(1월 3째 월)
        h.add(java.time.LocalDate.of(year, 2, 1).with(w));   // 워싱턴 탄생일(2월 3째 월)
        h.add(java.time.LocalDate.of(year, 5, 1).with(java.time.temporal.TemporalAdjusters.lastInMonth(java.time.DayOfWeek.MONDAY)));            // 메모리얼(5월 마지막 월)
        h.add(java.time.LocalDate.of(year, 9, 1).with(java.time.temporal.TemporalAdjusters.dayOfWeekInMonth(1, java.time.DayOfWeek.MONDAY)));    // 노동절(9월 1째 월)
        h.add(java.time.LocalDate.of(year, 11, 1).with(java.time.temporal.TemporalAdjusters.dayOfWeekInMonth(4, java.time.DayOfWeek.THURSDAY))); // 추수감사절(11월 4째 목)
        // Good Friday = 부활절 2일 전
        h.add(easterSunday(year).minusDays(2));
        return h;
    }

    /** 그레고리력 부활절(Meeus/Jones/Butcher 알고리즘). */
    private static java.time.LocalDate easterSunday(int year) {
        int a = year % 19, b = year / 100, c = year % 100;
        int dd = b / 4, e = b % 4, f = (b + 8) / 25, g = (b - f + 1) / 3;
        int hh = (19 * a + b - dd - g + 15) % 30;
        int i = c / 4, k = c % 4;
        int l = (32 + 2 * e + 2 * i - hh - k) % 7;
        int m = (a + 11 * hh + 22 * l) / 451;
        int month = (hh + l - 7 * m + 114) / 31;
        int day = ((hh + l - 7 * m + 114) % 31) + 1;
        return java.time.LocalDate.of(year, month, day);
    }

    /** 기사 발행 시각이 속하는 미국 거래 세션(마감일).
     *  16:00 ET 마감 이전이면 그 날 세션, 이후면 다음 거래일. 주말·휴장은 다음 거래일로 이월. */
    private static java.time.LocalDate tradingSession(java.time.Instant t) {
        java.time.ZonedDateTime et = t.atZone(MARKET_ZONE);
        java.time.LocalDate d = et.toLocalDate();
        if (et.toLocalTime().isAfter(MARKET_CLOSE)) d = d.plusDays(1);
        while (marketClosed(d)) d = d.plusDays(1);
        return d;
    }

    private static double absScore(Map<String, Object> a) {
        Object s = a.get("sentimentScore");
        return s == null ? 0 : Math.abs(((Number) s).doubleValue());
    }

    /** 종목 멀티데이 이벤트 타임라인 — 미국 거래 세션(16:00 ET 마감) 단위로 묶어 최근 N개 세션 반환 */
    @GetMapping("/ticker-timeline")
    public ResponseEntity<Map<String, Object>> tickerTimeline(
            @RequestHeader("X-Admin-Key") String adminKey,
            @RequestParam String ticker,
            @RequestParam(defaultValue = "5") int sessions) {
        requireAdmin(adminKey);
        String sym = ticker.replace("\"", "").strip().toUpperCase();
        if (!sym.matches("[A-Z][A-Z.\\-]{0,11}")) {
            return ResponseEntity.badRequest().body(Map.of("error", "유효하지 않은 ticker"));
        }
        int want = Math.min(Math.max(sessions, 1), 10);
        // 세션 want개를 채우려면 주말·휴장 고려해 넉넉히 조회
        java.time.Instant since = java.time.Instant.now().minus(java.time.Duration.ofDays(want * 3L + 7L));

        List<Map<String, Object>> rows = jdbc.query(
                """
                SELECT headline_ko, sentiment_label, sentiment_score, published_at
                FROM news_articles
                WHERE ? = ANY(tickers)
                  AND headline_ko IS NOT NULL AND headline_ko ~ '[가-힣ㄱ-ㅎㅏ-ㅣ]'
                  AND sentiment_reason IS NOT NULL
                  AND published_at >= ?
                ORDER BY published_at DESC
                """,
                (rs, i) -> {
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("headlineKo", rs.getString("headline_ko"));
                    m.put("sentimentLabel", rs.getString("sentiment_label"));
                    Object sc = rs.getObject("sentiment_score");
                    m.put("sentimentScore", sc == null ? null : ((Number) sc).doubleValue());
                    java.sql.Timestamp ts = rs.getTimestamp("published_at");
                    m.put("_instant", ts == null ? null : ts.toInstant());
                    return m;
                },
                sym, java.sql.Timestamp.from(since));

        java.util.TreeMap<java.time.LocalDate, List<Map<String, Object>>> bySession = new java.util.TreeMap<>();
        for (Map<String, Object> r : rows) {
            java.time.Instant inst = (java.time.Instant) r.get("_instant");
            if (inst == null) continue;
            bySession.computeIfAbsent(tradingSession(inst), k -> new java.util.ArrayList<>()).add(r);
        }

        List<java.time.LocalDate> dates = new java.util.ArrayList<>(bySession.keySet());
        if (dates.size() > want) dates = dates.subList(dates.size() - want, dates.size());

        List<Map<String, Object>> out = new java.util.ArrayList<>();
        for (java.time.LocalDate date : dates) {
            List<Map<String, Object>> arts = bySession.get(date);
            arts.sort((a, b) -> Double.compare(absScore(b), absScore(a)));
            double sum = 0; int n = 0;
            for (Map<String, Object> a : arts) {
                Object s = a.get("sentimentScore");
                if (s != null) { sum += ((Number) s).doubleValue(); n++; }
            }
            double avg = n > 0 ? sum / n : 0;
            String sentiment = avg > 0.15 ? "positive" : avg < -0.15 ? "negative" : "neutral";
            List<Map<String, Object>> top = new java.util.ArrayList<>();
            for (Map<String, Object> a : arts.subList(0, Math.min(2, arts.size()))) {
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("headlineKo", a.get("headlineKo"));
                m.put("sentimentLabel", a.get("sentimentLabel"));
                m.put("sentimentScore", a.get("sentimentScore"));
                top.add(m);
            }
            Map<String, Object> sess = new LinkedHashMap<>();
            sess.put("date", date.toString());
            sess.put("label", date.getMonthValue() + "/" + date.getDayOfMonth());
            sess.put("count", arts.size());
            sess.put("sentiment", sentiment);
            sess.put("avgScore", Math.round(avg * 100) / 100.0);
            sess.put("articles", top);
            out.add(sess);
        }

        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("ticker", sym);
        resp.put("sessions", out);
        return ResponseEntity.ok(resp);
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
