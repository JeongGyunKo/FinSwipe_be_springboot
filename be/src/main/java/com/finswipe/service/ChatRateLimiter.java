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
 * 사용자별 챗봇 레이트리밋.
 * - POST /chat/message: 분당 20회 (LLM 호출 비용 제한)
 * - GET  /chat/messages: 분당 60회 (히스토리 조회)
 */
@Component
public class ChatRateLimiter {

    public static final int RPM = 20;
    public static final int HISTORY_RPM = 60;
    public static final int MSG_MAX_CHARS = 500;

    private final Cache<UUID, Bucket> buckets = Caffeine.newBuilder()
            .expireAfterAccess(5, TimeUnit.MINUTES)
            .maximumSize(50_000)
            .build();

    private final Cache<UUID, Bucket> historyBuckets = Caffeine.newBuilder()
            .expireAfterAccess(5, TimeUnit.MINUTES)
            .maximumSize(50_000)
            .build();

    /** POST /chat/message — 토큰 소비 */
    public ProbeResult probe(UUID userId) {
        Bucket bucket = buckets.get(userId, k -> newBucket(RPM));
        ConsumptionProbe cp = bucket.tryConsumeAndReturnRemaining(1);
        return new ProbeResult(cp.isConsumed(), cp.getRemainingTokens(), cp.getNanosToWaitForRefill(), RPM);
    }

    /** GET /chat/messages — 토큰 소비 */
    public ProbeResult probeHistory(UUID userId) {
        Bucket bucket = historyBuckets.get(userId, k -> newBucket(HISTORY_RPM));
        ConsumptionProbe cp = bucket.tryConsumeAndReturnRemaining(1);
        return new ProbeResult(cp.isConsumed(), cp.getRemainingTokens(), cp.getNanosToWaitForRefill(), HISTORY_RPM);
    }

    /** 토큰 소비 없이 POST 버킷 상태만 조회 (내용 검증 실패 시 헤더용) */
    public ProbeResult peek(UUID userId) {
        Bucket bucket = buckets.get(userId, k -> newBucket(RPM));
        long available = bucket.getAvailableTokens();
        return new ProbeResult(true, available, 0, RPM);
    }

    private Bucket newBucket(int capacity) {
        return Bucket.builder()
                .addLimit(Bandwidth.builder()
                        .capacity(capacity)
                        .refillGreedy(capacity, Duration.ofMinutes(1))
                        .build())
                .build();
    }

    public record ProbeResult(boolean allowed, long remaining, long nanosToWait, int limit) {
        public long retryAfterSeconds() {
            return TimeUnit.NANOSECONDS.toSeconds(nanosToWait) + 1;
        }
        public long resetEpochSeconds() {
            return System.currentTimeMillis() / 1000 + retryAfterSeconds();
        }
    }
}
