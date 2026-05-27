package com.finswipe.config;

import lombok.RequiredArgsConstructor;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
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
                .requestFactory(factory(props.getGenai().getConnectTimeoutSeconds(),
                        props.getGenai().getReadTimeoutSeconds()))
                .build();
    }

    @Bean("genaiHealthRestClient")
    public RestClient genaiHealthRestClient() {
        return RestClient.builder()
                .baseUrl(props.getGenai().getUrl())
                .defaultHeader("Authorization", buildBasicAuth())
                .requestFactory(factory(10, 30))
                .build();
    }

    private String buildBasicAuth() {
        String credentials = props.getGenai().getUser() + ":" + props.getGenai().getPassword();
        return "Basic " + Base64.getEncoder().encodeToString(credentials.getBytes(StandardCharsets.UTF_8));
    }

    private SimpleClientHttpRequestFactory factory(int connectSec, int readSec) {
        SimpleClientHttpRequestFactory f = new SimpleClientHttpRequestFactory();
        f.setConnectTimeout(Duration.ofSeconds(connectSec));
        f.setReadTimeout(Duration.ofSeconds(readSec));
        return f;
    }

    @Bean("finlightRestClient")
    public RestClient finlightRestClient() {
        return RestClient.builder()
                .baseUrl(props.getFinlight().getBaseUrl())
                .defaultHeader("X-API-KEY", props.getFinlight().getApiKey())
                .requestFactory(factory(10, 60))
                .build();
    }
}
