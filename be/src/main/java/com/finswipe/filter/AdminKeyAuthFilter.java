package com.finswipe.filter;

import com.finswipe.config.AppProperties;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.List;

/**
 * 어드민 도구(admin.html, card-preview.html 등)가 X-Admin-Key로 뉴스 조회(read) 엔드포인트에
 * 접근할 수 있게 하는 보안 필터.
 *
 * <p>유효한 admin 키일 때만 비-UUID 'admin-tool' 프린시펄로 인증을 설정한다.
 * 적용 경로를 뉴스 read GET 전용으로 제한하므로 개인 데이터(/user, /chat 등)에는 영향이 없고,
 * 프린시펄이 UUID가 아니어서 개인화도 적용되지 않는다 → admin 키로도 일반 뉴스만 조회 가능(최소 권한).
 */
public class AdminKeyAuthFilter extends OncePerRequestFilter {

    private final AppProperties props;

    public AdminKeyAuthFilter(AppProperties props) {
        this.props = props;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest req, HttpServletResponse res, FilterChain chain)
            throws ServletException, IOException {
        if (isNewsRead(req) && SecurityContextHolder.getContext().getAuthentication() == null) {
            String provided = req.getHeader("X-Admin-Key");
            String expected = props.getAdmin().getApiKey();
            if (provided != null && expected != null && MessageDigest.isEqual(
                    provided.getBytes(StandardCharsets.UTF_8), expected.getBytes(StandardCharsets.UTF_8))) {
                var auth = new UsernamePasswordAuthenticationToken(
                        "admin-tool", null, List.of(new SimpleGrantedAuthority("ROLE_ADMIN")));
                SecurityContextHolder.getContext().setAuthentication(auth);
            }
        }
        chain.doFilter(req, res);
    }

    /** admin 키 인증을 허용할 경로 — 뉴스 조회 read GET 전용 */
    private static boolean isNewsRead(HttpServletRequest req) {
        if (!"GET".equalsIgnoreCase(req.getMethod())) return false;
        String uri = req.getRequestURI();
        return uri.equals("/news/latest")
                || uri.equals("/news/search")
                || uri.equals("/news/tickers")
                || (uri.startsWith("/news/tickers/") && uri.endsWith("/sentiment-trend"));
    }
}
