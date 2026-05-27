package com.finswipe.controller;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/auth")
@RequiredArgsConstructor
@Slf4j
public class AuthController {

    private final JdbcTemplate jdbc;

    record FindEmailRequest(@NotBlank String loginId) {}
    record FindLoginIdRequest(@NotBlank String email) {}

    /** Python: POST /auth/find-email — login_id로 마스킹된 이메일 조회 */
    @PostMapping("/find-email")
    public ResponseEntity<Map<String, String>> findEmail(@Valid @RequestBody FindEmailRequest body) {
        try {
            List<String> rows = jdbc.queryForList(
                    "SELECT email FROM user_profiles WHERE login_id = ?",
                    String.class, body.loginId().strip());

            if (rows.isEmpty()) {
                return ResponseEntity.status(HttpStatus.NOT_FOUND)
                        .body(Map.of("detail", "해당 아이디로 가입된 계정을 찾을 수 없습니다."));
            }
            String email = rows.get(0);
            if (email == null || email.isBlank()) {
                return ResponseEntity.status(HttpStatus.NOT_FOUND)
                        .body(Map.of("detail", "이메일 정보가 없습니다."));
            }
            return ResponseEntity.ok(Map.of("masked_email", maskEmail(email)));
        } catch (Exception e) {
            log.error("[이메일 찾기] 오류: {}", e.getMessage());
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                    .body(Map.of("detail", "서버 오류가 발생했습니다."));
        }
    }

    /** Python: POST /auth/find-login-id — 이메일로 login_id 조회 */
    @PostMapping("/find-login-id")
    public ResponseEntity<Map<String, String>> findLoginId(@Valid @RequestBody FindLoginIdRequest body) {
        try {
            List<String> rows = jdbc.queryForList(
                    "SELECT login_id FROM user_profiles WHERE email = ?",
                    String.class, body.email().strip().toLowerCase());

            if (rows.isEmpty()) {
                return ResponseEntity.status(HttpStatus.NOT_FOUND)
                        .body(Map.of("detail", "해당 이메일로 가입된 계정을 찾을 수 없습니다."));
            }
            String loginId = rows.get(0);
            if (loginId == null || loginId.isBlank()) {
                return ResponseEntity.status(HttpStatus.NOT_FOUND)
                        .body(Map.of("detail", "아이디 정보가 없습니다."));
            }
            return ResponseEntity.ok(Map.of("login_id", loginId));
        } catch (Exception e) {
            log.error("[아이디 찾기] 오류: {}", e.getMessage());
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                    .body(Map.of("detail", "서버 오류가 발생했습니다."));
        }
    }

    /** Python: _mask_email() — sw22tm1dn1ght@gmail.com → sw2***@gmail.com */
    private String maskEmail(String email) {
        try {
            int at = email.indexOf('@');
            if (at < 0) return "***@***.com";
            String local = email.substring(0, at);
            String domain = email.substring(at);
            String maskedLocal = local.substring(0, Math.min(3, local.length())) + "***";
            return maskedLocal + domain;
        } catch (Exception e) {
            return "***@***.com";
        }
    }
}
