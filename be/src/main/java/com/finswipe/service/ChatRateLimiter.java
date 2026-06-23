package com.finswipe.service;

import com.github.benmanes.caffeine.cache.Caffeine;
import com.github.benmanes.caffeine.cache.LoadingCache;
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
 *
 * LoadingCache 사용: 동일 키 동시 접근 시 Bucket이 단 한 번만 생성됨 (Caffeine 보장).
 * Cache.get(key, fn) 비사용 — 동시 요청 시 여러 Bucket 인스턴스가 생성되어 rate limit이 우회될 수 있음.
 */
@Component
public class ChatRateLimiter {

    public static final int RPM = 20;
    public static final int HISTORY_RPM = 60;
    public static final int MSG_MAX_CHARS = 500;

    private final LoadingCache<UUID, Bucket> buckets = Caffeine.newBuilder()
            .expireAfterAccess(5, TimeUnit.MINUTES)
            .maximumSize(50_000)
            .build(k -> newBucket(RPM));

    private final LoadingCache<UUID, Bucket> historyBuckets = Caffeine.newBuilder()
            .expireAfterAccess(5, TimeUnit.MINUTES)
            .maximumSize(50_000)
            .build(k -> newBucket(HISTORY_RPM));

    /** POST /chat/message — 토큰 소비 */
    public ProbeResult probe(UUID userId) {
        Bucket bucket = buckets.get(userId);
        ConsumptionProbe cp = bucket.tryConsumeAndReturnRemaining(1);
        return new ProbeResult(cp.isConsumed(), cp.getRemainingTokens(), cp.getNanosToWaitForRefill(), RPM);
    }

    /** GET /chat/messages — 토큰 소비 */
    public ProbeResult probeHistory(UUID userId) {
        Bucket bucket = historyBuckets.get(userId);
        ConsumptionProbe cp = bucket.tryConsumeAndReturnRemaining(1);
        return new ProbeResult(cp.isConsumed(), cp.getRemainingTokens(), cp.getNanosToWaitForRefill(), HISTORY_RPM);
    }

    /** 토큰 소비 없이 POST 버킷 상태만 조회 (내용 검증 실패 시 헤더용) */
    public ProbeResult peek(UUID userId) {
        Bucket bucket = buckets.get(userId);
        long available = bucket.getAvailableTokens();
        return new ProbeResult(true, available, 0, RPM);
    }

    private Bucket newBucket(int capacity) {
        return Bucket.builder()
                .addLimit(Bandwidth.builder()
                        .capacity(capacity)
                        .refillGreedy(capacity, Duration.ofMinutes(1))
                        .initialTokens(capacity)
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
