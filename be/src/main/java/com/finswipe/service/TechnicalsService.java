package com.finswipe.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.finswipe.dto.response.NewsArticleResponse.IndicatorSnapshot;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.cache.annotation.Cacheable;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClientResponseException;
import org.springframework.web.client.RestClient;

import static com.finswipe.config.CacheConfig.CACHE_TECHNICALS;

@Service
@Slf4j
public class TechnicalsService {

    private final RestClient genaiClient;
    private final ObjectMapper objectMapper;

    public TechnicalsService(@Qualifier("genaiRestClient") RestClient genaiClient,
                             ObjectMapper objectMapper) {
        this.genaiClient = genaiClient;
        this.objectMapper = objectMapper;
    }

    @Cacheable(value = CACHE_TECHNICALS, key = "#ticker")
    public IndicatorSnapshot getRsiSnapshot(String ticker) {
        try {
            String response = genaiClient.get()
                    .uri("/api/v1/technicals/{ticker}", ticker)
                    .retrieve()
                    .body(String.class);

            JsonNode root = objectMapper.readTree(response);
            if (!root.has("RSI") || root.get("RSI").isNull()) return null;

            double rsi = root.get("RSI").asDouble();
            String label;
            String captionSuffix;
            if (rsi >= 70) {
                label = "과매수";
                captionSuffix = "단기 과열 구간이에요.";
            } else if (rsi <= 30) {
                label = "과매도";
                captionSuffix = "저점 매수 관심 구간이에요.";
            } else {
                label = "중립";
                captionSuffix = "안정적인 구간이에요.";
            }
            String caption = String.format("RSI %.1f — %s", rsi, captionSuffix);

            return new IndicatorSnapshot("RSI", rsi, label, caption);
        } catch (RestClientResponseException e) {
            log.warn("[기술적지표] {} HTTP {}: {}", ticker, e.getStatusCode().value(), e.getMessage());
            return null;
        } catch (Exception e) {
            log.warn("[기술적지표] {} 조회 실패: {}", ticker, e.getMessage());
            return null;
        }
    }
}
