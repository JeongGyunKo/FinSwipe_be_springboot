package com.finswipe.config;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

@Component
@RequiredArgsConstructor
@Slf4j
public class FlywayConfig implements ApplicationRunner {

    private final JdbcTemplate jdbc;

    @Override
    public void run(ApplicationArguments args) {
        try {
            jdbc.execute("""
                    ALTER TABLE news_articles
                        ADD COLUMN IF NOT EXISTS event_category      TEXT,
                        ADD COLUMN IF NOT EXISTS sentiment_divergence BOOLEAN,
                        ADD COLUMN IF NOT EXISTS novelty_score        DOUBLE PRECISION
                    """);
            log.info("[SchemaPatch] event_category / sentiment_divergence / novelty_score 컬럼 보정 완료");
        } catch (Exception e) {
            log.error("[SchemaPatch] 컬럼 추가 실패: {}", e.getMessage());
        }
    }
}
