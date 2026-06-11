package com.finswipe.config;

import com.github.benmanes.caffeine.cache.Caffeine;
import lombok.RequiredArgsConstructor;
import org.springframework.cache.CacheManager;
import org.springframework.cache.caffeine.CaffeineCacheManager;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.util.concurrent.TimeUnit;

@Configuration
@RequiredArgsConstructor
public class CacheConfig {

    public static final String CACHE_NEWS_LATEST = "newsLatest";
    public static final String CACHE_NEWS_SEARCH = "newsSearch";
    public static final String CACHE_TICKERS = "tickers";
    public static final String CACHE_TECHNICALS = "technicals";

    private final AppProperties props;

    @Bean
    public CacheManager cacheManager() {
        CaffeineCacheManager manager = new CaffeineCacheManager();

        // 뉴스 캐시: TTL 60초, 페이지 offset 기준 500 엔트리
        manager.registerCustomCache(CACHE_NEWS_LATEST, Caffeine.newBuilder()
                .expireAfterWrite(60, TimeUnit.SECONDS)
                .maximumSize(500)
                .build());

        // 검색 캐시: 5분 TTL (검색 결과는 덜 자주 변함)
        manager.registerCustomCache(CACHE_NEWS_SEARCH, Caffeine.newBuilder()
                .expireAfterWrite(300, TimeUnit.SECONDS)
                .maximumSize(1000)
                .build());

        // 티커 목록: 1시간 TTL
        manager.registerCustomCache(CACHE_TICKERS, Caffeine.newBuilder()
                .expireAfterWrite(props.getCache().getTickersTtlSeconds(), TimeUnit.SECONDS)
                .maximumSize(10)
                .build());

        // 기술적 지표: 1시간 TTL, 티커당 1회 GenAI 호출
        manager.registerCustomCache(CACHE_TECHNICALS, Caffeine.newBuilder()
                .expireAfterWrite(3600, TimeUnit.SECONDS)
                .maximumSize(500)
                .build());

        return manager;
    }
}
