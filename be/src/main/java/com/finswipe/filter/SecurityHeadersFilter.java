package com.finswipe.filter;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;

@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class SecurityHeadersFilter extends OncePerRequestFilter {

    private static final String SWAGGER_CSP =
            "default-src 'self'; " +
            "script-src 'self' 'unsafe-inline'; " +
            "style-src 'self' 'unsafe-inline'; " +
            "img-src 'self' data:; " +
            "connect-src 'self'";

    private static final String PREVIEW_CSP =
            "default-src 'none'; " +
            "style-src 'unsafe-inline'; " +
            "script-src 'unsafe-inline'; " +
            "connect-src 'self'; " +
            "img-src 'self' data:";

    private static final String ADMIN_CSP =
            "default-src 'none'; " +
            "script-src 'unsafe-inline' 'unsafe-eval' https://cdn.tailwindcss.com https://cdn.jsdelivr.net; " +
            "style-src 'unsafe-inline' https://cdn.tailwindcss.com; " +
            "connect-src 'self' https://api.finswipe.co.kr; " +
            "img-src 'self' data:; " +
            "frame-src 'self'";

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain filterChain) throws ServletException, IOException {
        response.setHeader("X-Content-Type-Options", "nosniff");
        response.setHeader("Strict-Transport-Security", "max-age=31536000; includeSubDomains");
        response.setHeader("X-XSS-Protection", "1; mode=block");
        response.setHeader("Referrer-Policy", "strict-origin-when-cross-origin");

        String path = request.getRequestURI();
        // card-preview는 admin.html iframe 내부에서 로드되므로 SAMEORIGIN 허용
        if ("/card-preview.html".equals(path)) {
            response.setHeader("X-Frame-Options", "SAMEORIGIN");
        } else {
            response.setHeader("X-Frame-Options", "DENY");
        }
        if (path.startsWith("/swagger-ui") || path.startsWith("/v3/api-docs")) {
            response.setHeader("Content-Security-Policy", SWAGGER_CSP);
        } else if ("/preview.html".equals(path) || "/card-preview.html".equals(path)) {
            response.setHeader("Content-Security-Policy", PREVIEW_CSP);
        } else if ("/admin.html".equals(path) || "/digest.html".equals(path)) {
            response.setHeader("Content-Security-Policy", ADMIN_CSP);
        } else {
            response.setHeader("Content-Security-Policy", "default-src 'none'");
        }

        filterChain.doFilter(request, response);
    }
}
