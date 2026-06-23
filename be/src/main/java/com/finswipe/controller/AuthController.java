package com.finswipe.controller;

import com.finswipe.config.AppProperties;
import com.finswipe.dto.request.*;
import com.finswipe.service.AuthService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.media.Content;
import io.swagger.v3.oas.annotations.media.ExampleObject;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;

import java.net.URI;

import java.util.List;
import java.util.Map;

@Tag(name = "Auth", description = "회원가입 · 로그인 · 비밀번호 재설정")
@RestController
@RequestMapping("/auth")
@RequiredArgsConstructor
@Slf4j
public class AuthController {

    private final JdbcTemplate jdbc;
    private final AuthService authService;
    private final AppProperties props;

    // ── 회원가입 ──────────────────────────────────────────────────────────────

    @Operation(summary = "이메일 회원가입", description = "가입 후 인증 메일 발송. 메일 링크 클릭 후 로그인 가능.")
    @ApiResponse(responseCode = "201", content = @Content(examples = @ExampleObject(value = """
            { "message": "회원가입 완료. 이메일 인증 후 로그인해주세요.", "email": "user@example.com" }
            """)))
    @PostMapping("/register")
    public ResponseEntity<Map<String, Object>> register(@Valid @RequestBody RegisterRequest body) {
        try {
            return ResponseEntity.status(HttpStatus.CREATED)
                    .body(authService.register(body.email(), body.password(), body.displayName(), body.loginId()));
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        }
    }

    // ── 로그인 ────────────────────────────────────────────────────────────────

    @Operation(summary = "이메일 로그인", description = "성공 시 access_token 반환 (유효기간 90일)")
    @ApiResponse(responseCode = "200", content = @Content(examples = @ExampleObject(value = """
            {
              "access_token": "eyJhbGciOiJIUzI1NiJ9...",
              "token_type": "Bearer",
              "user_id": "550e8400-e29b-41d4-a716-446655440000",
              "email": "user@example.com",
              "display_name": "홍길동"
            }
            """)))
    @PostMapping("/login")
    public ResponseEntity<Map<String, Object>> login(@Valid @RequestBody LoginRequest body) {
        try {
            return ResponseEntity.ok(authService.login(body.email(), body.password()));
        } catch (IllegalArgumentException e) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED).body(Map.of("error", e.getMessage()));
        } catch (IllegalStateException e) {
            return ResponseEntity.status(HttpStatus.FORBIDDEN).body(Map.of("error", e.getMessage()));
        }
    }

    // ── Google 로그인 ─────────────────────────────────────────────────────────

    @Operation(summary = "Google 로그인", description = "FE에서 Google Sign-In SDK로 받은 idToken 전달. 신규 사용자는 자동 가입. 성공 시 access_token 반환 (유효기간 90일)")
    @ApiResponse(responseCode = "200", content = @Content(examples = @ExampleObject(value = """
            {
              "access_token": "eyJhbGciOiJIUzI1NiJ9...",
              "token_type": "Bearer",
              "user_id": "550e8400-e29b-41d4-a716-446655440000",
              "email": "user@gmail.com",
              "display_name": "홍길동"
            }
            """)))
    @PostMapping("/google")
    public ResponseEntity<Map<String, Object>> googleLogin(@Valid @RequestBody GoogleAuthRequest body) {
        try {
            return ResponseEntity.ok(authService.googleLogin(body.idToken()));
        } catch (IllegalArgumentException e) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED).body(Map.of("error", e.getMessage()));
        } catch (Exception e) {
            log.error("[Google] 로그인 처리 중 오류: {}: {}", e.getClass().getSimpleName(), e.getMessage(), e);
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                    .body(Map.of("error", "서버 오류"));
        }
    }

    // ── 이메일 인증 ───────────────────────────────────────────────────────────

    @Operation(summary = "이메일 인증 확인", description = "인증 메일의 링크에 포함된 token으로 계정 활성화 후 로그인 페이지로 리다이렉트")
    @GetMapping("/verify-email")
    public ResponseEntity<Void> verifyEmail(@RequestParam String token) {
        String frontendBase = props.getAuth().getFrontendBaseUrl();
        try {
            authService.verifyEmail(token);
            return ResponseEntity.status(HttpStatus.FOUND)
                    .location(URI.create(frontendBase + "/login?verified=true"))
                    .build();
        } catch (IllegalArgumentException e) {
            return ResponseEntity.status(HttpStatus.FOUND)
                    .location(URI.create(frontendBase + "/login?error=invalid_token"))
                    .build();
        }
    }

    // ── 이메일 중복 확인 ──────────────────────────────────────────────────────

    @Operation(summary = "이메일 중복 확인", description = "사용 가능 여부 확인. available=true면 사용 가능. Google 계정 이메일인 경우 reason=google 반환.")
    @ApiResponse(responseCode = "200", content = @Content(examples = @ExampleObject(value = """
            { "available": false, "reason": "google", "message": "Google 계정으로 이미 가입된 이메일입니다. Google 로그인을 이용해주세요." }
            """)))
    @GetMapping("/check-email")
    public ResponseEntity<Map<String, Object>> checkEmail(@RequestParam String email) {
        if (email == null || email.isBlank()) {
            return ResponseEntity.badRequest().body(Map.of("error", "이메일을 입력해주세요."));
        }
        String normalized = email.strip().toLowerCase();
        try {
            List<String> rows = jdbc.queryForList(
                    "SELECT auth_provider FROM user_profiles WHERE email = ?",
                    String.class, normalized);
            if (rows.isEmpty()) {
                return ResponseEntity.ok(Map.of("available", true));
            }
            String provider = rows.get(0);
            if ("google".equals(provider)) {
                return ResponseEntity.ok(Map.of(
                        "available", false,
                        "reason", "google",
                        "message", "Google 계정으로 이미 가입된 이메일입니다. Google 로그인을 이용해주세요."));
            }
            return ResponseEntity.ok(Map.of("available", false, "message", "이미 사용 중인 이메일입니다."));
        } catch (Exception e) {
            log.error("[이메일 중복확인] 오류: {}", e.getMessage());
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                    .body(Map.of("error", "서버 오류"));
        }
    }

    // ── 아이디 중복 확인 ──────────────────────────────────────────────────────

    @Operation(summary = "아이디 중복 확인", description = "사용 가능 여부 확인. available=true면 사용 가능.")
    @ApiResponse(responseCode = "200", content = @Content(examples = @ExampleObject(value = """
            { "available": true }
            """)))
    @GetMapping("/check-login-id")
    public ResponseEntity<Map<String, Object>> checkLoginId(@RequestParam String loginId) {
        if (loginId == null || loginId.isBlank() || loginId.length() < 2 || loginId.length() > 20) {
            return ResponseEntity.badRequest().body(Map.of("error", "아이디는 2~20자여야 합니다"));
        }
        try {
            // 아이디는 대소문자 구분 — 원본 케이스로 비교·반환
            String trimmed = loginId.strip();
            Integer count = jdbc.queryForObject(
                    "SELECT COUNT(*) FROM user_profiles WHERE login_id = ?",
                    Integer.class, trimmed);
            boolean available = count == null || count == 0;
            return ResponseEntity.ok(Map.of("available", available, "loginId", trimmed));
        } catch (Exception e) {
            log.error("[아이디 중복확인] 오류: {}", e.getMessage());
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                    .body(Map.of("error", "서버 오류"));
        }
    }

    // ── 비밀번호 재설정 ───────────────────────────────────────────────────────

    @Operation(summary = "비밀번호 재설정 요청", description = "이메일로 재설정 링크 발송 (1시간 유효). 미가입 이메일·Google 계정은 400 반환.")
    @ApiResponse(responseCode = "200", content = @Content(examples = @ExampleObject(value = """
            { "message": "비밀번호 재설정 링크를 이메일로 발송했습니다." }
            """)))
    @PostMapping("/forgot-password")
    public ResponseEntity<Map<String, Object>> forgotPassword(@Valid @RequestBody ForgotPasswordRequest body) {
        try {
            authService.forgotPassword(body.email());
            return ResponseEntity.ok(Map.of("message", "비밀번호 재설정 링크를 이메일로 발송했습니다."));
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        }
    }

    @Operation(summary = "비밀번호 재설정", description = "재설정 메일의 token과 새 비밀번호(8자 이상) 전달")
    @ApiResponse(responseCode = "200", content = @Content(examples = @ExampleObject(value = """
            { "message": "비밀번호가 변경되었습니다." }
            """)))
    @PostMapping("/reset-password")
    public ResponseEntity<Map<String, Object>> resetPassword(@Valid @RequestBody ResetPasswordRequest body) {
        try {
            authService.resetPassword(body.token(), body.newPassword());
            return ResponseEntity.ok(Map.of("message", "비밀번호가 변경되었습니다."));
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
        } catch (Exception e) {
            log.error("[비밀번호 재설정] 오류: {}", e.getMessage(), e);
            return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                    .body(Map.of("error", "서버 오류가 발생했습니다. 잠시 후 다시 시도해주세요."));
        }
    }

    // ── 기존 엔드포인트 유지 ──────────────────────────────────────────────────

    record FindEmailRequest(@NotBlank String loginId) {}
    record FindLoginIdRequest(@NotBlank String email) {}

    @PostMapping("/find-email")
    public ResponseEntity<Map<String, String>> findEmail(@Valid @RequestBody FindEmailRequest body) {
        try {
            List<String> rows = jdbc.queryForList(
                    "SELECT email FROM user_profiles WHERE login_id = ?",
                    String.class, body.loginId().strip());
            String email = rows.isEmpty() ? null : rows.get(0);
            // 계정 존재 여부를 노출하지 않고 항상 동일한 응답 반환 (열거 공격 방지)
            return ResponseEntity.ok(Map.of(
                    "masked_email", (email != null && !email.isBlank()) ? maskEmail(email) : ""));
        } catch (Exception e) {
            log.error("[이메일 찾기] 오류: {}", e.getMessage(), e);
            return ResponseEntity.ok(Map.of("masked_email", ""));
        }
    }

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

    private String maskEmail(String email) {
        try {
            int at = email.indexOf('@');
            if (at < 0) return "***@***.com";
            String local = email.substring(0, at);
            String domain = email.substring(at);
            return local.substring(0, Math.min(3, local.length())) + "***" + domain;
        } catch (Exception e) {
            return "***@***.com";
        }
    }
}
