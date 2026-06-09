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

    public AdminController(JdbcTemplate jdbc,
                           AppProperties props,
                           @Qualifier("genaiRestClient") RestClient genaiClient) {
        this.jdbc = jdbc;
        this.props = props;
        this.genaiClient = genaiClient;
    }

    /** 전체 유저 목록 — 프리뷰 도구용 */
    @GetMapping("/users")
    public ResponseEntity<List<Map<String, Object>>> users(
            @RequestHeader("X-Admin-Key") String adminKey) {
        requireAdmin(adminKey);
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
                    // tickers: PostgreSQL array → List
                    String raw = rs.getString("tickers");
                    m.put("tickers", parseTickers(raw));
                    return m;
                });
        return ResponseEntity.ok(rows);
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

    private List<String> parseTickers(String raw) {
        if (raw == null || raw.equals("{}") || raw.isBlank()) return List.of();
        String inner = raw.substring(1, raw.length() - 1).trim();
        if (inner.isBlank()) return List.of();
        return List.of(inner.split(","));
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
