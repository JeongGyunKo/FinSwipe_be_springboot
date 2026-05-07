package com.finswipe.filter;

import com.finswipe.config.AppProperties;
import com.finswipe.util.IpExtractorUtil;
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
import java.time.Duration;
import java.util.concurrent.ConcurrentHashMap;

@Component
@Order(10)
@RequiredArgsConstructor
public class RateLimitFilter extends OncePerRequestFilter {

    private final AppProperties props;
    private final ConcurrentHashMap<String, Bucket> buckets = new ConcurrentHashMap<>();

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain filterChain) throws ServletException, IOException {
        String ip = IpExtractorUtil.extractRealIp(request);
        boolean isAdmin = request.getRequestURI().startsWith("/news/") && isAdminEndpoint(request);

        int rpm = isAdmin ? props.getRateLimit().getAdminRpm() : props.getRateLimit().getPublicRpm();
        String key = ip + ":" + (isAdmin ? "admin" : "public");

        Bucket bucket = buckets.computeIfAbsent(key, k -> buildBucket(rpm));

        if (bucket.tryConsume(1)) {
            filterChain.doFilter(request, response);
        } else {
            response.setStatus(HttpStatus.TOO_MANY_REQUESTS.value());
            response.setContentType(MediaType.APPLICATION_JSON_VALUE);
            response.getWriter().write("{\"error\":\"Rate limit exceeded. Please slow down.\"}");
        }
    }

    private boolean isAdminEndpoint(HttpServletRequest request) {
        return request.getHeader("X-Admin-Key") != null;
    }

    private Bucket buildBucket(int rpm) {
        Bandwidth limit = Bandwidth.builder()
                .capacity(rpm)
                .refillGreedy(rpm, Duration.ofMinutes(1))
                .build();
        return Bucket.builder().addLimit(limit).build();
    }
}
