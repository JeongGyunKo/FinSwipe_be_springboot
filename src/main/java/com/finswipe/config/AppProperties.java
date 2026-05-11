package com.finswipe.config;

import jakarta.validation.Valid;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import lombok.Getter;
import lombok.Setter;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.context.annotation.Configuration;
import org.springframework.validation.annotation.Validated;

import java.util.List;

@Configuration
@ConfigurationProperties(prefix = "app")
@Validated
@Getter
@Setter
public class AppProperties {

    @Valid
    private Finlight finlight = new Finlight();

    @Valid
    private Genai genai = new Genai();

    @Valid
    private Admin admin = new Admin();

    private Cors cors = new Cors();
    private Cache cache = new Cache();
    @Valid
    private RateLimit rateLimit = new RateLimit();
    private Fcm fcm = new Fcm();

    @Getter
    @Setter
    public static class Finlight {
        @NotBlank
        private String apiKey;
        private String baseUrl = "https://api.finlight.me";
    }

    @Getter
    @Setter
    public static class Genai {
        @NotBlank
        private String url;
        @NotBlank
        private String user;
        @NotBlank
        private String password;
        private int connectTimeoutSeconds = 10;
        private int readTimeoutSeconds = 300;
        private int concurrentRequests = 3;   // 동시 GenAI 요청 수 (Semaphore)
        private int enrichmentThreads = 5;    // 분석 스레드 풀 크기
    }

    @Getter
    @Setter
    public static class Admin {
        @NotBlank
        @Size(min = 16, message = "Admin API key must be at least 16 characters")
        private String apiKey;
    }

    @Getter
    @Setter
    public static class Cors {
        private List<String> origins = List.of("*");
    }

    @Getter
    @Setter
    public static class Cache {
        private int newsTtlSeconds = 30;
        private int tickersTtlSeconds = 3600;
    }

    @Getter
    @Setter
    public static class RateLimit {
        @Min(1)
        private int publicRpm = 30;
        @Min(1)
        private int adminRpm = 300;
    }

    @Getter
    @Setter
    public static class Fcm {
        private String serviceAccountJson = "";
        private String projectId = "";
        private String clientEmail = "";
        private String privateKey = "";
    }
}
