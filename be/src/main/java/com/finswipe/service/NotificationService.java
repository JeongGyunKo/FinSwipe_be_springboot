package com.finswipe.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.security.KeyFactory;
import java.security.PrivateKey;
import java.security.Signature;
import java.security.spec.PKCS8EncodedKeySpec;
import java.time.Duration;
import java.util.Base64;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;

@Service
@RequiredArgsConstructor
@Slf4j
public class NotificationService {

    private static final String TOKEN_URL = "https://oauth2.googleapis.com/token";
    private static final String FCM_SEND_URL = "https://fcm.googleapis.com/v1/projects/%s/messages:send";
    private static final String FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging";

    private final JdbcTemplate jdbc;
    private final ObjectMapper objectMapper;
    private final HttpClient httpClient = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(10))
            .build();

    // OAuth 토큰 캐시 — 만료 5분 전에 재발급 (Google 토큰 유효시간 1시간)
    private final AtomicReference<String> cachedToken = new AtomicReference<>();
    private volatile long tokenExpiresAt = 0;

    /** Base64로 인코딩된 경우 디코딩 — MIME → 표준 순서로 시도 */
    private String decodeIfBase64(String value) {
        if (value == null || value.isBlank()) return value;
        String trimmed = value.trim();
        // 값 전체가 따옴표로 감싸인 경우만 외부 따옴표 제거 (JSON 내부 따옴표는 유지)
        if ((trimmed.startsWith("\"") && trimmed.endsWith("\""))
                || (trimmed.startsWith("'") && trimmed.endsWith("'"))) {
            trimmed = trimmed.substring(1, trimmed.length() - 1).trim();
        }
        if (trimmed.startsWith("{")) return trimmed;

        // 잘린 패딩 자동 보정
        int rem = trimmed.length() % 4;
        String padded = trimmed;
        if (rem == 2) padded += "==";
        else if (rem == 3) padded += "=";

        for (Base64.Decoder decoder : List.of(
                Base64.getMimeDecoder(), Base64.getDecoder(), Base64.getUrlDecoder())) {
            try {
                String decoded = new String(decoder.decode(padded),
                        java.nio.charset.StandardCharsets.UTF_8).trim();
                if (decoded.startsWith("{")) return decoded;
            } catch (Exception ignored) {}
        }
        log.warn("[알림] Base64 디코딩 실패 → 원본 값 사용");
        return trimmed;
    }

    /** Python: notify_ticker_article() */
    public void notifyTickerArticle(String headline, List<String> tickers, String serviceAccountJson) {
        serviceAccountJson = decodeIfBase64(serviceAccountJson);
        List<String> tokens = getTokensForTickers(tickers);
        if (tokens.isEmpty()) return;

        String tickerStr = String.join(", ", tickers.subList(0, Math.min(3, tickers.size())));
        String body = headline.length() > 80 ? headline.substring(0, 80) + "..." : headline;

        sendPush(
                "📈 " + tickerStr + " 관련 새 뉴스",
                body,
                serviceAccountJson,
                tokens,
                Map.of("type", "ticker_article", "tickers", String.join(",", tickers))
        );
    }

    /** Python: _get_tokens_for_tickers() */
    private List<String> getTokensForTickers(List<String> tickers) {
        if (tickers == null || tickers.isEmpty()) return List.of();
        try {
            // user_profiles에서 해당 티커 관심 등록 사용자 조회
            String tickerArray = "{" + String.join(",", tickers) + "}";
            List<String> userIds = jdbc.queryForList(
                    "SELECT id::text FROM user_profiles WHERE tickers && ?::text[]",
                    String.class, tickerArray);
            if (userIds.isEmpty()) return List.of();

            // device_tokens에서 알림 활성화된 토큰 조회 — 파라미터화 쿼리로 SQL Injection 방지
            String placeholders = String.join(",", java.util.Collections.nCopies(userIds.size(), "?"));
            return jdbc.queryForList(
                    "SELECT token FROM device_tokens WHERE user_id::text IN (" + placeholders + ") AND notify_all_news = true",
                    String.class, userIds.toArray());
        } catch (Exception e) {
            log.error("[알림] 티커 기반 토큰 조회 실패: {}", e.getMessage());
            return List.of();
        }
    }

    /** Python: send_push() */
    public void sendPush(String title, String body, String serviceAccountJson,
                         List<String> tokens, Map<String, String> data) {
        if (serviceAccountJson == null || serviceAccountJson.isBlank()) {
            log.warn("[알림] FCM_SERVICE_ACCOUNT_JSON 미설정 → 알림 스킵");
            return;
        }
        if (tokens.isEmpty()) {
            log.info("[알림] 발송 대상 토큰 없음 → 스킵");
            return;
        }

        try {
            log.debug("[알림] FCM JSON 길이={}", serviceAccountJson.length());
            Map<?, ?> info = objectMapper.readValue(serviceAccountJson, Map.class);
            String projectId = (String) info.get("project_id");
            String accessToken = getOrRefreshAccessToken(serviceAccountJson, info);
            if (accessToken == null) return;

            String url = String.format(FCM_SEND_URL, projectId);
            int success = 0, failed = 0;

            for (String token : tokens) {
                Map<String, Object> notification = Map.of("title", title, "body", body);
                Map<String, String> dataMap = new HashMap<>(data != null ? data : Map.of());
                Map<String, Object> message = Map.of("token", token, "notification", notification, "data", dataMap);
                String payload = objectMapper.writeValueAsString(Map.of("message", message));

                HttpRequest req = HttpRequest.newBuilder()
                        .uri(URI.create(url))
                        .header("Authorization", "Bearer " + accessToken)
                        .header("Content-Type", "application/json")
                        .POST(HttpRequest.BodyPublishers.ofString(payload, StandardCharsets.UTF_8))
                        .timeout(Duration.ofSeconds(10))
                        .build();

                HttpResponse<String> resp = httpClient.send(req, HttpResponse.BodyHandlers.ofString());
                if (resp.statusCode() == 200) {
                    success++;
                } else {
                    failed++;
                    String respBody = resp.body();
                    log.warn("[알림] FCM 발송 실패: {} {}", resp.statusCode(),
                            respBody.length() > 100 ? respBody.substring(0, 100) : respBody);
                    // 만료/유효하지 않은 토큰 → DB에서 삭제
                    if (resp.statusCode() == 404 || resp.statusCode() == 400) {
                        jdbc.update("DELETE FROM device_tokens WHERE token = ?", token);
                        log.info("[알림] 만료 토큰 삭제: {}…", token.length() > 20 ? token.substring(0, 20) : token);
                    }
                }
            }
            log.info("[알림] 발송 완료 → 성공 {}개 / 실패 {}개", success, failed);

        } catch (Exception e) {
            log.error("[알림] 발송 오류: {}", e.getMessage());
        }
    }

    /** 토큰 캐싱 래퍼 — 만료 5분 전까지 기존 토큰 재사용 */
    private String getOrRefreshAccessToken(String serviceAccountJson, Map<?, ?> info) {
        long now = System.currentTimeMillis();
        String token = cachedToken.get();
        if (token != null && now < tokenExpiresAt) {
            return token;
        }
        String newToken = getAccessToken(serviceAccountJson, info);
        if (newToken != null) {
            cachedToken.set(newToken);
            tokenExpiresAt = now + Duration.ofMinutes(55).toMillis(); // 1시간 유효, 5분 여유
        }
        return newToken;
    }

    /**
     * Python: _get_access_token() — 서비스 계정 JSON으로 OAuth 2.0 액세스 토큰 발급.
     * google-auth 라이브러리 없이 순수 Java 암호화로 구현 (JWT RS256 서명 → 토큰 교환).
     */
    @SuppressWarnings("unchecked")
    private String getAccessToken(String serviceAccountJson, Map<?, ?> info) {
        try {
            String clientEmail = (String) info.get("client_email");
            String privateKeyPem = (String) info.get("private_key");

            // PEM → PKCS8 키 파싱
            String keyBase64 = privateKeyPem
                    .replace("-----BEGIN PRIVATE KEY-----", "")
                    .replace("-----END PRIVATE KEY-----", "")
                    .replaceAll("\\s+", "");
            byte[] keyBytes = Base64.getDecoder().decode(keyBase64);
            PrivateKey privateKey = KeyFactory.getInstance("RSA")
                    .generatePrivate(new PKCS8EncodedKeySpec(keyBytes));

            // JWT 헤더 + 페이로드 생성
            long now = System.currentTimeMillis() / 1000;
            String header = Base64.getUrlEncoder().withoutPadding().encodeToString(
                    "{\"alg\":\"RS256\",\"typ\":\"JWT\"}".getBytes(StandardCharsets.UTF_8));
            String payloadJson = String.format(
                    "{\"iss\":\"%s\",\"scope\":\"%s\",\"aud\":\"%s\",\"iat\":%d,\"exp\":%d}",
                    clientEmail, FCM_SCOPE, TOKEN_URL, now, now + 3600);
            String payloadB64 = Base64.getUrlEncoder().withoutPadding().encodeToString(
                    payloadJson.getBytes(StandardCharsets.UTF_8));

            // RS256 서명
            String toSign = header + "." + payloadB64;
            Signature sig = Signature.getInstance("SHA256withRSA");
            sig.initSign(privateKey);
            sig.update(toSign.getBytes(StandardCharsets.UTF_8));
            String signature = Base64.getUrlEncoder().withoutPadding().encodeToString(sig.sign());
            String jwt = toSign + "." + signature;

            // 토큰 교환
            String formBody = "grant_type=urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Ajwt-bearer&assertion=" + jwt;
            HttpRequest req = HttpRequest.newBuilder()
                    .uri(URI.create(TOKEN_URL))
                    .header("Content-Type", "application/x-www-form-urlencoded")
                    .POST(HttpRequest.BodyPublishers.ofString(formBody, StandardCharsets.UTF_8))
                    .timeout(Duration.ofSeconds(10))
                    .build();

            HttpResponse<String> resp = httpClient.send(req, HttpResponse.BodyHandlers.ofString());
            Map<String, Object> tokenResponse = objectMapper.readValue(resp.body(), Map.class);
            return (String) tokenResponse.get("access_token");

        } catch (Exception e) {
            log.error("[알림] 액세스 토큰 발급 실패: {}", e.getMessage());
            return null;
        }
    }
}
