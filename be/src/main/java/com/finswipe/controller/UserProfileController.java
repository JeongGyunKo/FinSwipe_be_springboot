package com.finswipe.controller;

import com.finswipe.service.NewsCollectorService;
import io.swagger.v3.oas.annotations.Operation;
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
                    "SELECT tickers, level FROM user_profiles WHERE id = CAST(? AS UUID)",
                    (rs, row) -> {
                        List<String> tickers = parseTickers(rs.getString("tickers"));
                        Integer level = (Integer) rs.getObject("level");
                        return ResponseEntity.ok(Map.<String, Object>of(
                                "userId", uid,
                                "tickers", tickers,
                                "level", level != null ? level : 0
                        ));
                    }, uid);
        } catch (EmptyResultDataAccessException e) {
            return ResponseEntity.status(HttpStatus.NOT_FOUND)
                    .body(Map.of("error", "사용자를 찾을 수 없습니다"));
        } catch (Exception e) {
            log.error("[프로필] 조회 실패: {}", e.getMessage());
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                    .body(Map.of("error", "서버 오류"));
        }
    }

    @Operation(summary = "관심 티커 업데이트", description = "티커 목록 전체 교체. 신규 추가된 티커는 최근 7일치 뉴스 소급 분석 자동 실행.")
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
            List<String> newTickers = body.tickers() != null ? body.tickers() : List.of();
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

    @Operation(summary = "투자 레벨 저장", description = "퀴즈 완료 후 산출된 레벨(1~5) 저장")
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
        return List.of(inner.split(","));
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
