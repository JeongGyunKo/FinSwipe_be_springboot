package com.finswipe.config;

import lombok.extern.slf4j.Slf4j;
import org.flywaydb.core.Flyway;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import javax.sql.DataSource;

@Configuration
@Slf4j
public class FlywayConfig {

    @Bean(initMethod = "migrate")
    public Flyway flyway(DataSource dataSource,
                         @Value("${spring.flyway.baseline-on-migrate:true}") boolean baselineOnMigrate,
                         @Value("${spring.flyway.baseline-version:0}") String baselineVersion,
                         @Value("${spring.flyway.validate-on-migrate:false}") boolean validateOnMigrate) {
        log.info("[Flyway] 마이그레이션 시작 (validateOnMigrate={})", validateOnMigrate);
        return Flyway.configure()
                .dataSource(dataSource)
                .baselineOnMigrate(baselineOnMigrate)
                .baselineVersion(baselineVersion)
                .validateOnMigrate(validateOnMigrate)
                .locations("classpath:db/migration")
                .load();
    }
}
