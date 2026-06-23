package com.finswipe.filter;

import com.finswipe.config.AppProperties;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Base64;

/**
 * 스웨거 문서(/swagger-ui, /v3/api-docs)에 HTTP Basic 인증 게이트를 적용하는 보안 필터.
 *
 * <p>비밀번호는 환경변수(SWAGGER_PASSWORD)로만 주입하며 코드/저장소에 두지 않는다.
 * 비밀번호가 비어 있으면 스웨거 경로 접근을 전면 차단한다(fail-closed) — 실수로 공개되는 것을 방지.
 * 사용자/비밀번호 비교는 상수 시간(MessageDigest.isEqual)으로 수행해 타이밍 공격을 막는다.
 *
 * <p>실제 API 호출은 별도 JWT 인증이 필요하므로, 이 게이트의 목적은 "API 문서(구조) 외부 노출 차단"이다.
 */
public class SwaggerBasicAuthFilter extends OncePerRequestFilter {

    private static final String REALM = "FinSwipe API Docs";

    private final String user;
    private final String password;

    public SwaggerBasicAuthFilter(AppProperties props) {
        this.user = props.getSwagger().getUser();
        this.password = props.getSwagger().getPassword();
    }

    @Override
    protected void doFilterInternal(HttpServletRequest req, HttpServletResponse res, FilterChain chain)
            throws ServletException, IOException {
        if (!isSwaggerPath(req)) {
            chain.doFilter(req, res);
            return;
        }
        // 비밀번호 미설정 → 전면 차단(fail-closed). 빈 비번으로의 우회를 막는다.
        if (password == null || password.isBlank()) {
            unauthorized(res);
            return;
        }
        String header = req.getHeader("Authorization");
        if (header != null && header.startsWith("Basic ")) {
            try {
                String decoded = new String(
                        Base64.getDecoder().decode(header.substring(6).trim()), StandardCharsets.UTF_8);
                int sep = decoded.indexOf(':');
                if (sep >= 0) {
                    String u = decoded.substring(0, sep);
                    String p = decoded.substring(sep + 1);
                    if (constantTimeEquals(u, user) && constantTimeEquals(p, password)) {
                        chain.doFilter(req, res);
                        return;
                    }
                }
            } catch (IllegalArgumentException ignored) {
                // base64 디코딩 실패 → 인증 실패로 처리
            }
        }
        unauthorized(res);
    }

    private void unauthorized(HttpServletResponse res) throws IOException {
        res.setHeader("WWW-Authenticate", "Basic realm=\"" + REALM + "\", charset=\"UTF-8\"");
        res.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
        res.setContentType("application/json;charset=UTF-8");
        res.getWriter().write("{\"error\":\"API 문서 접근 인증이 필요합니다.\"}");
    }

    private static boolean constantTimeEquals(String a, String b) {
        if (a == null || b == null) return false;
        return MessageDigest.isEqual(
                a.getBytes(StandardCharsets.UTF_8), b.getBytes(StandardCharsets.UTF_8));
    }

    /** Basic 인증을 요구할 경로 — 스웨거 UI / OpenAPI 문서 전용 */
    private static boolean isSwaggerPath(HttpServletRequest req) {
        String uri = req.getRequestURI();
        return uri.startsWith("/swagger-ui") || uri.startsWith("/v3/api-docs");
    }
}
