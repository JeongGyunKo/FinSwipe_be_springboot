package com.finswipe.config;

import lombok.RequiredArgsConstructor;
import org.apache.hc.client5.http.config.RequestConfig;
import org.apache.hc.client5.http.impl.classic.HttpClients;
import org.apache.hc.client5.http.impl.io.PoolingHttpClientConnectionManager;
import org.apache.hc.core5.util.Timeout;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.HttpComponentsClientHttpRequestFactory;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.RestClient;

import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Base64;

@Configuration
@RequiredArgsConstructor
public class RestClientConfig {

    private final AppProperties props;

    @Bean("genaiRestClient")
    public RestClient genaiRestClient() {
        return RestClient.builder()
                .baseUrl(props.getGenai().getUrl())
                .defaultHeader("Authorization", buildBasicAuth())
                .requestFactory(pooledFactory(
                        props.getGenai().getConnectTimeoutSeconds(),
                        props.getGenai().getReadTimeoutSeconds(),
                        20))  // GenAI 전용 연결 풀: 최대 20
                .build();
    }

    @Bean("genaiHealthRestClient")
    public RestClient genaiHealthRestClient() {
        return RestClient.builder()
                .baseUrl(props.getGenai().getUrl())
                .defaultHeader("Authorization", buildBasicAuth())
                .requestFactory(simpleFactory(10, 30))
                .build();
    }

    @Bean("finlightRestClient")
    public RestClient finlightRestClient() {
        return RestClient.builder()
                .baseUrl(props.getFinlight().getBaseUrl())
                .defaultHeader("X-API-KEY", props.getFinlight().getApiKey())
                .requestFactory(simpleFactory(10, 60))
                .build();
    }

    private String buildBasicAuth() {
        String credentials = props.getGenai().getUser() + ":" + props.getGenai().getPassword();
        return "Basic " + Base64.getEncoder().encodeToString(credentials.getBytes(StandardCharsets.UTF_8));
    }

    /** Apache HttpClient 5 연결 풀 기반 팩토리 — 반복 요청 시 TCP 재사용 */
    private HttpComponentsClientHttpRequestFactory pooledFactory(int connectSec, int readSec, int maxConnections) {
        PoolingHttpClientConnectionManager connManager = new PoolingHttpClientConnectionManager();
        connManager.setMaxTotal(maxConnections);
        connManager.setDefaultMaxPerRoute(maxConnections);

        RequestConfig requestConfig = RequestConfig.custom()
                .setConnectTimeout(Timeout.ofSeconds(connectSec))
                .setResponseTimeout(Timeout.ofSeconds(readSec))
                .setConnectionRequestTimeout(Timeout.ofSeconds(5))
                .build();

        var httpClient = HttpClients.custom()
                .setConnectionManager(connManager)
                .setDefaultRequestConfig(requestConfig)
                .evictExpiredConnections()
                .build();

        return new HttpComponentsClientHttpRequestFactory(httpClient);
    }

    private SimpleClientHttpRequestFactory simpleFactory(int connectSec, int readSec) {
        SimpleClientHttpRequestFactory f = new SimpleClientHttpRequestFactory();
        f.setConnectTimeout(Duration.ofSeconds(connectSec));
        f.setReadTimeout(Duration.ofSeconds(readSec));
        return f;
    }
}
