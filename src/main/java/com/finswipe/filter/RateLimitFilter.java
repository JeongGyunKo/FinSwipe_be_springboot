package com.finswipe.filter;

import com.finswipe.config.AppProperties;
import com.finswipe.util.IpExtractorUtil;
import com.github.benmanes.caffeine.cache.Cache;
import com.github.benmanes.caffeine.cache.Caffeine;
import io.github.bucket4j.Bandwidth;
import io.github.bucket4j.Bucket;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.core.annotation.Order;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.security.MessageDigest;
import java.time.Duration;

@Component
@Order(10)
@RequiredArgsConstructor
public class RateLimitFilter extends OncePerRequestFilter {

    private final AppProperties props;
    // Caffeine으로 교체 — 1시간 미접속 IP 자동 만료, 최대 50,000 IP 보관
    private final Cache<String, Bucket> buckets = Caffeine.newBuilder()
            .expireAfterAccess(Duration.ofHours(1))
            .maximumSize(50_000)
            .build();

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain filterChain) throws ServletException, IOException {
        // 헬스체크는 rate limit 제외 (k8s probe 등)
        if ("/health".equals(request.getRequestURI())) {
            filterChain.doFilter(request, response);
            return;
        }

        String ip = IpExtractorUtil.extractRealIp(request);
        boolean isAdmin = request.getRequestURI().startsWith("/news/") && isAdminEndpoint(request);

        int rpm = isAdmin ? props.getRateLimit().getAdminRpm() : props.getRateLimit().getPublicRpm();
        String key = ip + ":" + (isAdmin ? "admin" : "public");

        Bucket bucket = buckets.get(key, k -> buildBucket(rpm));

        if (bucket.tryConsume(1)) {
            filterChain.doFilter(request, response);
        } else {
            response.setStatus(HttpStatus.TOO_MANY_REQUESTS.value());
            response.setContentType(MediaType.APPLICATION_JSON_VALUE);
            response.getWriter().write("{\"error\":\"Rate limit exceeded. Please slow down.\"}");
        }
    }

    private boolean isAdminEndpoint(HttpServletRequest request) {
        String provided = request.getHeader("X-Admin-Key");
        if (provided == null) return false;
        String expected = props.getAdmin().getApiKey();
        return expected != null && MessageDigest.isEqual(provided.getBytes(), expected.getBytes());
    }

    private Bucket buildBucket(int rpm) {
        Bandwidth limit = Bandwidth.builder()
                .capacity(rpm)
                .refillGreedy(rpm, Duration.ofMinutes(1))
                .build();
        return Bucket.builder().addLimit(limit).build();
    }
}
