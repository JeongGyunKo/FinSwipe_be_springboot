package com.finswipe.controller;

import com.finswipe.service.NewsCollectorService;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.media.Content;
import io.swagger.v3.oas.annotations.media.ExampleObject;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.security.SecurityRequirement;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.EmptyResultDataAccessException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;
import java.util.UUID;

@Tag(name = "User", description = "사용자 프로필 · 관심 티커 · 투자 레벨 관리")
@SecurityRequirement(name = "bearerAuth")
@RestController
@RequestMapping("/user")
@RequiredArgsConstructor
@Slf4j
public class UserProfileController {

    private final JdbcTemplate jdbc;
    private final NewsCollectorService collectorService;

    @Operation(summary = "프로필 조회", description = "관심 티커 목록과 퀴즈로 측정된 투자 레벨 반환 (레벨 0 = 미측정)")
    @ApiResponse(responseCode = "200", content = @Content(examples = @ExampleObject(value = """
            {
              "userId": "550e8400-e29b-41d4-a716-446655440000",
              "email": "user@gmail.com",
              "displayName": "홍길동",
              "loginId": "user123",
              "authProvider": "google",
              "tickers": ["AAPL", "TSLA", "NVDA"],
              "level": 3,
              "tendency": "모멘텀형 투자자",
              "newsSort": "time"
            }
            """)))
    @GetMapping("/profile")
    public ResponseEntity<Map<String, Object>> getProfile(
            Authentication auth,
            @RequestParam(required = false) String userId) {
        final String uid = resolveUserId(auth, userId);
        if (uid == null) return ResponseEntity.badRequest().body(Map.of("error", "userId 필요"));
        if (!isValidUuid(uid)) {
            return ResponseEntity.badRequest().body(Map.of("error", "유효하지 않은 userId"));
        }
        try {
            return jdbc.queryForObject(
                    "SELECT tickers, level, tendency, email, display_name, login_id, auth_provider, news_sort FROM user_profiles WHERE id = CAST(? AS UUID)",
                    (rs, row) -> {
                        List<String> tickers = parseTickers(rs.getString("tickers"));
                        Object rawLevel = rs.getObject("level");
                        Integer level = rawLevel != null ? ((Number) rawLevel).intValue() : null;
                        java.util.Map<String, Object> body = new java.util.LinkedHashMap<>();
                        body.put("userId", uid);
                        body.put("email", rs.getString("email"));
                        body.put("displayName", rs.getString("display_name"));
                        body.put("loginId", rs.getString("login_id"));
                        body.put("authProvider", rs.getString("auth_provider"));
                        body.put("tickers", tickers);
                        body.put("level", level != null ? level : 0);
                        body.put("tendency", rs.getString("tendency") != null ? rs.getString("tendency") : "탐색형 투자자");
                        body.put("newsSort", rs.getString("news_sort") != null ? rs.getString("news_sort") : "time");
                        return ResponseEntity.ok(body);
                    }, uid);
        } catch (EmptyResultDataAccessException e) {
            return ResponseEntity.status(HttpStatus.NOT_FOUND)
                    .body(Map.of("error", "사용자를 찾을 수 없습니다"));
        } catch (Exception e) {
            log.error("[프로필] 조회 실패 [{}]: {}", e.getClass().getSimpleName(), e.getMessage(), e);
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                    .body(Map.of("error", "서버 오류"));
        }
    }

    @Operation(summary = "내정보 수정", description = "displayName(닉네임), loginId(아이디), password(비밀번호) 중 포함된 필드만 수정. 비밀번호 변경은 email 가입자만 가능.")
    @ApiResponse(responseCode = "200", content = @Content(examples = @ExampleObject(value = """
            { "ok": true }
            """)))
    @PatchMapping("/profile")
    public ResponseEntity<Map<String, Object>> updateProfile(
            Authentication auth,
            @RequestParam(required = false) String userId,
            @RequestBody Map<String, String> body) {
        final String uid = resolveUserId(auth, userId);
        if (uid == null) return ResponseEntity.badRequest().body(Map.of("error", "userId 필요"));
        if (!isValidUuid(uid)) return ResponseEntity.badRequest().body(Map.of("error", "유효하지 않은 userId"));

        String displayName = body.get("displayName");
        String loginId = body.get("loginId");
        String password = body.get("password");

        if (displayName == null && loginId == null && password == null) {
            return ResponseEntity.badRequest().body(Map.of("error", "수정할 항목이 없습니다"));
        }

        if (displayName != null && (displayName.strip().length() < 2 || displayName.strip().length() > 30)) {
            return ResponseEntity.badRequest().body(Map.of("error", "닉네임은 2~30자여야 합니다"));
        }
        if (loginId != null && (loginId.strip().length() < 2 || loginId.strip().length() > 20)) {
            return ResponseEntity.badRequest().body(Map.of("error", "아이디는 2~20자여야 합니다"));
        }
        if (password != null && password.length() > 128) {
            return ResponseEntity.badRequest().body(Map.of("error", "비밀번호는 128자를 초과할 수 없습니다"));
        }

        try {
            if (displayName != null && !displayName.isBlank()) {
                jdbc.update("UPDATE user_profiles SET display_name = ?, updated_at = NOW() WHERE id = CAST(? AS UUID)",
                        displayName.strip(), uid);
            }
            if (loginId != null && !loginId.isBlank()) {
                // 아이디는 대소문자 구분 — 원본 케이스 보존
                String loginIdValue = loginId.strip();
                Integer exists = jdbc.queryForObject(
                        "SELECT COUNT(*) FROM user_profiles WHERE login_id = ? AND id != CAST(? AS UUID)",
                        Integer.class, loginIdValue, uid);
                if (exists != null && exists > 0) {
                    return ResponseEntity.badRequest().body(Map.of("error", "이미 사용 중인 아이디입니다"));
                }
                jdbc.update("UPDATE user_profiles SET login_id = ?, updated_at = NOW() WHERE id = CAST(? AS UUID)",
                        loginIdValue, uid);
            }
            if (password != null && !password.isBlank()) {
                String provider = jdbc.queryForObject(
                        "SELECT auth_provider FROM user_profiles WHERE id = CAST(? AS UUID)", String.class, uid);
                if (!"email".equals(provider)) {
                    return ResponseEntity.badRequest().body(Map.of("error", "소셜 로그인 계정은 비밀번호를 변경할 수 없습니다"));
                }
                if (password.length() < 8) {
                    return ResponseEntity.badRequest().body(Map.of("error", "비밀번호는 8자 이상이어야 합니다"));
                }
                String hashed = new BCryptPasswordEncoder().encode(password);
                jdbc.update("UPDATE user_profiles SET password_hash = ?, updated_at = NOW() WHERE id = CAST(? AS UUID)",
                        hashed, uid);
            }
            return ResponseEntity.ok(Map.of("ok", true));
        } catch (Exception e) {
            log.error("[프로필 수정] 실패: {}", e.getMessage());
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR).body(Map.of("error", "서버 오류"));
        }
    }

    @Operation(summary = "관심 티커 조회", description = "사용자의 관심 티커 목록 반환")
    @ApiResponse(responseCode = "200", content = @Content(examples = @ExampleObject(value = """
            {
              "tickers": ["AAPL", "TSLA", "NVDA"]
            }
            """)))
    @GetMapping("/tickers")
    public ResponseEntity<Map<String, Object>> getTickers(
            Authentication auth,
            @RequestParam(required = false) String userId) {
        final String uid = resolveUserId(auth, userId);
        if (uid == null) return ResponseEntity.badRequest().body(Map.of("error", "userId 필요"));
        if (!isValidUuid(uid)) {
            return ResponseEntity.badRequest().body(Map.of("error", "유효하지 않은 userId"));
        }
        try {
            String raw = jdbc.queryForObject(
                    "SELECT tickers FROM user_profiles WHERE id = CAST(? AS UUID)",
                    String.class, uid);
            return ResponseEntity.ok(Map.of("tickers", parseTickers(raw)));
        } catch (EmptyResultDataAccessException e) {
            return ResponseEntity.status(HttpStatus.NOT_FOUND)
                    .body(Map.of("error", "사용자를 찾을 수 없습니다"));
        } catch (Exception e) {
            log.error("[티커] 조회 실패: {}", e.getMessage());
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                    .body(Map.of("error", "서버 오류"));
        }
    }

    @Operation(summary = "관심 티커 업데이트", description = "티커 목록 전체 교체. 신규 추가된 티커는 최근 7일치 뉴스 소급 분석 자동 실행.")
    @ApiResponse(responseCode = "200", content = @Content(examples = @ExampleObject(value = """
            { "ok": true, "tickers": ["AAPL", "TSLA"], "triggered_analysis_for": ["TSLA"] }
            """)))
    @PutMapping("/tickers")
    public ResponseEntity<Map<String, Object>> updateTickers(
            Authentication auth,
            @RequestParam(required = false) String userId,
            @Valid @RequestBody TickersRequest body) {
        final String uid = resolveUserId(auth, userId);
        if (uid == null) return ResponseEntity.badRequest().body(Map.of("error", "userId 필요"));
        if (!isValidUuid(uid)) {
            return ResponseEntity.badRequest().body(Map.of("error", "유효하지 않은 userId"));
        }
        userId = uid;
        try {
            // 기존 티커 조회 — 새로 추가된 것만 소급 분석
            String rawOld;
            try {
                rawOld = jdbc.queryForObject(
                        "SELECT tickers FROM user_profiles WHERE id = CAST(? AS UUID)",
                        String.class, userId);
            } catch (EmptyResultDataAccessException e) {
                return ResponseEntity.status(HttpStatus.NOT_FOUND)
                        .body(Map.of("error", "사용자를 찾을 수 없습니다"));
            }

            List<String> oldTickers = parseTickers(rawOld);
            // 저장 전 정규화 — 따옴표/공백 제거 + 대문자 (FE가 q="NVDA"처럼 보내도 깨끗하게 저장)
            List<String> newTickers = (body.tickers() != null ? body.tickers() : List.<String>of())
                    .stream()
                    .map(t -> t.replace("\"", "").strip().toUpperCase())
                    .filter(s -> !s.isEmpty())
                    .distinct()
                    .toList();
            String tickersArray = newTickers.isEmpty() ? "{}" :
                    "{" + String.join(",", newTickers) + "}";

            jdbc.update(
                    "UPDATE user_profiles SET tickers = CAST(? AS TEXT[]), updated_at = NOW() WHERE id = CAST(? AS UUID)",
                    tickersArray, userId);

            // 신규 추가된 티커만 소급 분석 (최근 7일)
            List<String> addedTickers = newTickers.stream()
                    .filter(t -> !oldTickers.contains(t))
                    .toList();
            if (!addedTickers.isEmpty()) {
                log.info("[프로필] 신규 티커 {} → 소급 분석 트리거", addedTickers);
                Thread.ofVirtual().start(() ->
                        collectorService.triggerAnalysisForNewTickers(addedTickers));
            }

            return ResponseEntity.ok(Map.of(
                    "ok", true,
                    "tickers", newTickers,
                    "triggered_analysis_for", addedTickers
            ));
        } catch (Exception e) {
            log.error("[티커] 업데이트 실패: {}", e.getMessage());
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                    .body(Map.of("error", "서버 오류"));
        }
    }

    @Operation(summary = "뉴스 정렬 저장", description = "메인 뉴스 정렬 기준 저장. sort: time(시간순) | power(파워순)")
    @ApiResponse(responseCode = "200", content = @Content(examples = @ExampleObject(value = """
            { "ok": true, "newsSort": "power" }
            """)))
    @PutMapping("/news-sort")
    public ResponseEntity<Map<String, Object>> updateNewsSort(
            Authentication auth,
            @RequestParam(required = false) String userId,
            @RequestBody Map<String, String> body) {
        final String uid = resolveUserId(auth, userId);
        if (uid == null) return ResponseEntity.badRequest().body(Map.of("error", "userId 필요"));
        if (!isValidUuid(uid)) return ResponseEntity.badRequest().body(Map.of("error", "유효하지 않은 userId"));
        String sort = body.getOrDefault("sort", "time");
        if (!sort.equals("time") && !sort.equals("power")) {
            return ResponseEntity.badRequest().body(Map.of("error", "sort는 time 또는 power여야 합니다"));
        }
        try {
            jdbc.update("UPDATE user_profiles SET news_sort = ?, updated_at = NOW() WHERE id = CAST(? AS UUID)",
                    sort, uid);
            return ResponseEntity.ok(Map.of("ok", true, "newsSort", sort));
        } catch (Exception e) {
            log.error("[뉴스정렬] 저장 실패: {}", e.getMessage());
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR).body(Map.of("error", "서버 오류"));
        }
    }

    @Operation(summary = "투자 레벨 저장", description = "퀴즈 완료 후 산출된 레벨(1~5) 저장")
    @ApiResponse(responseCode = "200", content = @Content(examples = @ExampleObject(value = """
            { "ok": true, "level": 3 }
            """)))
    @PostMapping("/level")
    public ResponseEntity<Map<String, Object>> updateLevel(
            Authentication auth,
            @RequestParam(required = false) String userId,
            @Valid @RequestBody LevelRequest body) {
        final String uid = resolveUserId(auth, userId);
        if (uid == null) return ResponseEntity.badRequest().body(Map.of("error", "userId 필요"));
        if (!isValidUuid(uid)) {
            return ResponseEntity.badRequest().body(Map.of("error", "유효하지 않은 userId"));
        }
        userId = uid;
        try {
            int updated = jdbc.update(
                    "UPDATE user_profiles SET level = ?, updated_at = NOW() WHERE id = CAST(? AS UUID)",
                    body.level(), userId);
            if (updated == 0) {
                return ResponseEntity.status(HttpStatus.NOT_FOUND)
                        .body(Map.of("error", "사용자를 찾을 수 없습니다"));
            }
            log.info("[프로필] 레벨 업데이트: userId={} level={}", userId, body.level());
            return ResponseEntity.ok(Map.of("ok", true, "level", body.level()));
        } catch (Exception e) {
            log.error("[레벨] 업데이트 실패: {}", e.getMessage());
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                    .body(Map.of("error", "서버 오류"));
        }
    }

    // ── 내부 유틸 ──────────────────────────────────────────────────────────────

    /** JWT에서 userId 추출, 없으면 쿼리 파라미터 사용 */
    private String resolveUserId(Authentication auth, String queryParam) {
        if (auth != null && auth.getPrincipal() instanceof UUID) {
            return auth.getPrincipal().toString();
        }
        return queryParam;
    }

    private List<String> parseTickers(String raw) {
        if (raw == null || raw.equals("{}") || raw.isBlank()) return List.of();
        String inner = raw.substring(1, raw.length() - 1).trim();
        if (inner.isBlank()) return List.of();
        // Postgres 배열 따옴표/공백 제거 — 저장값에 따옴표가 섞여도 깨끗한 심볼 반환
        return java.util.Arrays.stream(inner.split(","))
                .map(s -> s.replace("\"", "").strip())
                .filter(s -> !s.isEmpty())
                .toList();
    }

    private static boolean isValidUuid(String value) {
        try { java.util.UUID.fromString(value); return true; }
        catch (IllegalArgumentException e) { return false; }
    }

    // ── Request Body ──────────────────────────────────────────────────────────

    record TickersRequest(
            @Size(max = 50, message = "티커는 최대 50개까지 등록 가능합니다")
            List<@NotBlank @Size(max = 10) String> tickers) {}

    record LevelRequest(
            @Min(1) @Max(5) int level) {}
}
