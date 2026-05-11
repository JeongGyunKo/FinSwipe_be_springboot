package com.finswipe.config;

import lombok.RequiredArgsConstructor;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.RestClient;

import java.time.Duration;
import java.util.Base64;

@Configuration
@RequiredArgsConstructor
public class RestClientConfig {

    private final AppProperties props;

    @Bean("genaiRestClient")
    public RestClient genaiRestClient() {
        String credentials = props.getGenai().getUser() + ":" + props.getGenai().getPassword();
        String basicAuth = "Basic " + Base64.getEncoder().encodeToString(credentials.getBytes());

        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(Duration.ofSeconds(props.getGenai().getConnectTimeoutSeconds()));
        factory.setReadTimeout(Duration.ofSeconds(props.getGenai().getReadTimeoutSeconds()));

        return RestClient.builder()
                .baseUrl(props.getGenai().getUrl())
                .defaultHeader("Authorization", basicAuth)
                .requestFactory(factory)
                .build();
    }

    @Bean("genaiHealthRestClient")
    public RestClient genaiHealthRestClient() {
        String credentials = props.getGenai().getUser() + ":" + props.getGenai().getPassword();
        String basicAuth = "Basic " + Base64.getEncoder().encodeToString(credentials.getBytes());

        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(Duration.ofSeconds(10));
        factory.setReadTimeout(Duration.ofSeconds(30));

        return RestClient.builder()
                .baseUrl(props.getGenai().getUrl())
                .defaultHeader("Authorization", basicAuth)
                .requestFactory(factory)
                .build();
    }

    @Bean("finlightRestClient")
    public RestClient finlightRestClient() {
        return RestClient.builder()
                .baseUrl(props.getFinlight().getBaseUrl())
                .defaultHeader("X-API-KEY", props.getFinlight().getApiKey())
                .build();
    }
}
