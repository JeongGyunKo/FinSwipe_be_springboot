package com.finswipe.service;

import com.finswipe.config.AppProperties;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;

import java.time.OffsetDateTime;
import java.util.Map;
import java.util.UUID;

@Service
@RequiredArgsConstructor
@Slf4j
public class AuthService {

    private final JdbcTemplate jdbc;
    private final JwtService jwtService;
    private final EmailService emailService;
    private final AppProperties props;
    private final BCryptPasswordEncoder passwordEncoder;

    // ── 이메일/비밀번호 회원가입 ──────────────────────────────────────────────
    public Map<String, Object> register(String email, String password, String displayName, String loginId) {
        String normalized = email.strip().toLowerCase();
        // 아이디는 대소문자 구분 — 원본 케이스 보존 (이메일만 소문자 정규화)
        String loginIdValue = loginId.strip();

        var existingProviders = jdbc.queryForList(
                "SELECT auth_provider FROM user_profiles WHERE email = ?", String.class, normalized);
        if (!existingProviders.isEmpty()) {
            if ("google".equals(existingProviders.get(0))) {
                throw new IllegalArgumentException("Google 계정으로 이미 가입된 이메일입니다. Google 로그인을 이용해주세요.");
            }
            throw new IllegalArgumentException("이미 사용 중인 이메일입니다.");
        }

        Integer loginIdCount = jdbc.queryForObject(
                "SELECT COUNT(*) FROM user_profiles WHERE login_id = ?", Integer.class, loginIdValue);
        if (loginIdCount != null && loginIdCount > 0) {
            throw new IllegalArgumentException("이미 사용 중인 아이디입니다.");
        }

        UUID userId = UUID.randomUUID();
        String hash = passwordEncoder.encode(password);
        String verifyToken = UUID.randomUUID().toString();

        jdbc.update("""
                INSERT INTO user_profiles
                    (id, email, display_name, password_hash, auth_provider, email_verified,
                     email_verify_token, login_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'email', false, ?, ?, NOW(), NOW())
                """, userId, normalized, displayName, hash, verifyToken, loginIdValue);

        emailService.sendVerificationEmail(normalized, verifyToken);
        log.info("[Auth] 회원가입 완료");

        return Map.of(
                "message", "회원가입 완료. 이메일 인증 후 로그인해주세요.",
                "email", normalized
        );
    }

    // ── 이메일/비밀번호 로그인 ────────────────────────────────────────────────
    public Map<String, Object> login(String email, String password) {
        String normalized = email.strip().toLowerCase();

        var row = jdbc.query("""
                SELECT id, password_hash, email_verified, display_name
                FROM user_profiles
                WHERE email = ? AND auth_provider = 'email'
                """,
                (rs, i) -> new Object[]{
                        rs.getObject("id", UUID.class),
                        rs.getString("password_hash"),
                        rs.getBoolean("email_verified"),
                        rs.getString("display_name")
                },
                normalized
        );

        if (row.isEmpty()) {
            throw new IllegalArgumentException("이메일 또는 비밀번호가 올바르지 않습니다.");
        }

        Object[] data = row.get(0);
        UUID userId = (UUID) data[0];
        String hash = (String) data[1];
        boolean verified = (boolean) data[2];
        String displayName = (String) data[3];

        if (!passwordEncoder.matches(password, hash)) {
            throw new IllegalArgumentException("이메일 또는 비밀번호가 올바르지 않습니다.");
        }
        if (!verified) {
            throw new IllegalStateException("이메일 인증이 필요합니다. 메일함을 확인해주세요.");
        }

        String token = jwtService.generateAccessToken(userId, normalized);
        log.info("[Auth] 로그인 완료");
        return buildAuthResponse(token, userId, normalized, displayName);
    }

    // ── Google 로그인 ─────────────────────────────────────────────────────────
    public Map<String, Object> googleLogin(String idToken) {
        Map<String, Object> googleUser = verifyGoogleToken(idToken);
        String email = (String) googleUser.get("email");
        String sub = (String) googleUser.get("sub");
        String name = (String) googleUser.getOrDefault("name", email);
        // Google tokeninfo는 email_verified를 문자열 "true"로 반환
        Object evRaw = googleUser.get("email_verified");
        boolean emailVerified = Boolean.TRUE.equals(evRaw) || "true".equalsIgnoreCase(String.valueOf(evRaw));
        log.info("[Google] email_verified raw={} parsed={}", evRaw, emailVerified);

        if (!emailVerified) {
            throw new IllegalArgumentException("Google 계정 이메일이 인증되지 않았습니다.");
        }

        log.info("[Google] 유저 조회 시작: email={} sub={}", email, sub);
        // 기존 유저 조회 (google_sub 또는 email)
        var existing = jdbc.query("""
                SELECT id, display_name FROM user_profiles
                WHERE google_sub = ? OR (email = ? AND auth_provider = 'google')
                """,
                (rs, i) -> new Object[]{rs.getObject("id", UUID.class), rs.getString("display_name")},
                sub, email
        );

        UUID userId;
        String displayName;

        if (!existing.isEmpty()) {
            userId = (UUID) existing.get(0)[0];
            displayName = (String) existing.get(0)[1];
            jdbc.update("UPDATE user_profiles SET updated_at = NOW() WHERE id = ?", userId);
        } else {
            userId = UUID.randomUUID();
            displayName = name;
            jdbc.update("""
                    INSERT INTO user_profiles
                        (id, email, display_name, auth_provider, email_verified, google_sub, created_at, updated_at)
                    VALUES (?, ?, ?, 'google', true, ?, NOW(), NOW())
                    """, userId, email, name, sub);
            log.info("[Auth] Google 신규 가입 완료");
        }

        String token = jwtService.generateAccessToken(userId, email);
        return buildAuthResponse(token, userId, email, displayName);
    }

    // ── 이메일 인증 ───────────────────────────────────────────────────────────
    public void verifyEmail(String token) {
        int updated = jdbc.update("""
                UPDATE user_profiles
                SET email_verified = true, email_verify_token = NULL, updated_at = NOW()
                WHERE email_verify_token = ? AND email_verified = false
                """, token);
        if (updated == 0) {
            throw new IllegalArgumentException("유효하지 않거나 이미 인증된 토큰입니다.");
        }
        log.info("[Auth] 이메일 인증 완료: token={}...", token.substring(0, 8));
    }

    // ── 비밀번호 재설정 요청 ──────────────────────────────────────────────────
    public void forgotPassword(String email) {
        String normalized = email.strip().toLowerCase();

        var rows = jdbc.queryForList(
                "SELECT auth_provider FROM user_profiles WHERE email = ?",
                String.class, normalized);

        if (rows.isEmpty()) {
            throw new IllegalArgumentException("가입되지 않은 이메일입니다.");
        }
        if ("google".equals(rows.get(0))) {
            throw new IllegalArgumentException("Google 계정으로 가입된 이메일입니다. Google 로그인을 이용해주세요.");
        }

        String resetToken = UUID.randomUUID().toString();
        OffsetDateTime expires = OffsetDateTime.now().plusHours(1);

        jdbc.update("""
                UPDATE user_profiles
                SET password_reset_token = ?, password_reset_expires = ?, updated_at = NOW()
                WHERE email = ? AND auth_provider = 'email'
                """, resetToken, expires, normalized);

        emailService.sendPasswordResetEmail(normalized, resetToken);
        log.info("[Auth] 비밀번호 재설정 요청: email={}", normalized);
    }

    // ── 비밀번호 재설정 ───────────────────────────────────────────────────────
    public void resetPassword(String token, String newPassword) {
        int updated = jdbc.update("""
                UPDATE user_profiles
                SET password_hash = ?, password_reset_token = NULL,
                    password_reset_expires = NULL, updated_at = NOW()
                WHERE password_reset_token = ?
                  AND password_reset_expires > NOW()
                """, passwordEncoder.encode(newPassword), token);
        if (updated == 0) {
            throw new IllegalArgumentException("유효하지 않거나 만료된 토큰입니다.");
        }
        log.info("[Auth] 비밀번호 재설정 완료");
    }

    // ── 내부 유틸 ─────────────────────────────────────────────────────────────

    @SuppressWarnings("unchecked")
    private Map<String, Object> verifyGoogleToken(String idToken) {
        try {
            var client = RestClient.create();
            java.net.URI tokenInfoUri = org.springframework.web.util.UriComponentsBuilder
                    .fromUriString("https://oauth2.googleapis.com/tokeninfo")
                    .queryParam("id_token", idToken)
                    .build()
                    .toUri();
            Map<String, Object> payload = client.get()
                    .uri(tokenInfoUri)
                    .retrieve()
                    .body(Map.class);

            // aud 검증
            String clientId = props.getAuth().getGoogleClientId();
            if (clientId != null && !clientId.isBlank()) {
                String aud = (String) payload.get("aud");
                if (!clientId.equals(aud)) {
                    throw new IllegalArgumentException("유효하지 않은 Google 토큰입니다.");
                }
            }

            // iss 검증 — Google이 발행한 토큰인지 확인
            String iss = (String) payload.get("iss");
            if (!"https://accounts.google.com".equals(iss) && !"accounts.google.com".equals(iss)) {
                throw new IllegalArgumentException("유효하지 않은 Google 토큰입니다.");
            }

            // exp 검증 — 만료 여부 확인
            Object expRaw = payload.get("exp");
            if (expRaw != null) {
                long exp = Long.parseLong(expRaw.toString());
                if (exp < System.currentTimeMillis() / 1000) {
                    throw new IllegalArgumentException("만료된 Google 토큰입니다.");
                }
            }

            return payload;
        } catch (IllegalArgumentException e) {
            throw e;
        } catch (Exception e) {
            log.error("[Google] tokeninfo 호출 실패: {}", e.getClass().getSimpleName());
            throw new IllegalArgumentException("유효하지 않은 Google 토큰입니다.");
        }
    }

    private Map<String, Object> buildAuthResponse(String token, UUID userId, String email, String displayName) {
        return Map.of(
                "access_token", token,
                "token_type", "Bearer",
                "user_id", userId.toString(),
                "email", email,
                "display_name", displayName != null ? displayName : ""
        );
    }
}
