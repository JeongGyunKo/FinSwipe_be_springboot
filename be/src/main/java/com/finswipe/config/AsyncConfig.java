package com.finswipe.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import jakarta.annotation.PreDestroy;
import lombok.RequiredArgsConstructor;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

@Configuration
@RequiredArgsConstructor
public class AsyncConfig {

    private final AppProperties props;
    private ExecutorService enrichmentExecutorRef;

    @Bean
    public ObjectMapper objectMapper() {
        return new ObjectMapper()
                .registerModule(new JavaTimeModule())
                .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS);
    }

    @Bean("enrichmentExecutor")
    public ExecutorService enrichmentExecutor() {
        enrichmentExecutorRef = Executors.newVirtualThreadPerTaskExecutor();
        return enrichmentExecutorRef;
    }

    @PreDestroy
    public void shutdownEnrichmentExecutor() {
        if (enrichmentExecutorRef == null) return;
        enrichmentExecutorRef.shutdown();
        try {
            if (!enrichmentExecutorRef.awaitTermination(30, TimeUnit.SECONDS)) {
                enrichmentExecutorRef.shutdownNow();
            }
        } catch (InterruptedException e) {
            enrichmentExecutorRef.shutdownNow();
            Thread.currentThread().interrupt();
        }
    }
}