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

    private Swagger swagger = new Swagger();

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
    public static class Swagger {
        /** 스웨거 문서 Basic 인증 사용자명 (기본값 finswipe) */
        private String user = "finswipe";
        /** 스웨거 문서 Basic 인증 비밀번호 — SWAGGER_PASSWORD 환경변수로만 주입. 비어 있으면 문서 접근 전면 차단. */
        private String password = "";
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
        @Min(1)
        private int quizRpm = 20;   // 비인증 퀴즈(POST /quiz) LLM 비용 어뷰즈 방지용 별도 한도
    }

    @Getter
    @Setter
    public static class Fcm {
        private String serviceAccountJson = "";
        private String projectId = "";
        private String clientEmail = "";
        private String privateKey = "";
    }

    @Valid
    private Auth auth = new Auth();

    @Getter
    @Setter
    public static class Auth {
        @NotBlank
        @Size(min = 32, message = "JWT 시크릿은 최소 32자 이상이어야 합니다")
        private String jwtSecret;
        private long accessTokenExpiryMs = 604800000L; // 7일
        private String googleClientId = "";
        private String appBaseUrl = "https://api.finswipe.co.kr";
        private String frontendBaseUrl = "https://www.finswipe.co.kr";
    }
}
