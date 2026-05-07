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

    private final AppProperties props;

    @Bean
    public CacheManager cacheManager() {
        CaffeineCacheManager manager = new CaffeineCacheManager();

        // 뉴스 캐시: 30초 TTL
        manager.registerCustomCache(CACHE_NEWS_LATEST, Caffeine.newBuilder()
                .expireAfterWrite(props.getCache().getNewsTtlSeconds(), TimeUnit.SECONDS)
                .maximumSize(100)
                .build());

        manager.registerCustomCache(CACHE_NEWS_SEARCH, Caffeine.newBuilder()
                .expireAfterWrite(props.getCache().getNewsTtlSeconds(), TimeUnit.SECONDS)
                .maximumSize(500)
                .build());

        // 티커 목록: 1시간 TTL
        manager.registerCustomCache(CACHE_TICKERS, Caffeine.newBuilder()
                .expireAfterWrite(props.getCache().getTickersTtlSeconds(), TimeUnit.SECONDS)
                .maximumSize(1)
                .build());

        return manager;
    }
}
