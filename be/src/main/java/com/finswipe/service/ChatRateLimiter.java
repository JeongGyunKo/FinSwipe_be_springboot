package com.finswipe.service;

import com.github.benmanes.caffeine.cache.Cache;
import com.github.benmanes.caffeine.cache.Caffeine;
import io.github.bucket4j.Bandwidth;
import io.github.bucket4j.Bucket;
import io.github.bucket4j.ConsumptionProbe;
import org.springframework.stereotype.Component;

import java.time.Duration;
import java.util.UUID;
import java.util.concurrent.TimeUnit;

/**
 * 사용자별 LLM 챗봇 레이트리밋.
 * 분당 20회, greedy 리필 (3초마다 1토큰).
 */
@Component
public class ChatRateLimiter {

    public static final int RPM = 20;
    public static final int MSG_MAX_CHARS = 500;

    private final Cache<UUID, Bucket> buckets = Caffeine.newBuilder()
            .expireAfterAccess(5, TimeUnit.MINUTES)
            .maximumSize(50_000)
            .build();

    public ProbeResult probe(UUID userId) {
        Bucket bucket = buckets.get(userId, k -> newBucket());
        ConsumptionProbe probe = bucket.tryConsumeAndReturnRemaining(1);
        return new ProbeResult(probe.isConsumed(), probe.getRemainingTokens(),
                probe.getNanosToWaitForRefill());
    }

    private Bucket newBucket() {
        return Bucket.builder()
                .addLimit(Bandwidth.builder()
                        .capacity(RPM)
                        .refillGreedy(RPM, Duration.ofMinutes(1))
                        .build())
                .build();
    }

    public record ProbeResult(boolean allowed, long remaining, long nanosToWait) {
        public long retryAfterSeconds() {
            return TimeUnit.NANOSECONDS.toSeconds(nanosToWait) + 1;
        }
    }
}
