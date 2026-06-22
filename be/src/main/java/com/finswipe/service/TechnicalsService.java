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

import java.util.ArrayList;
import java.util.List;

import static com.finswipe.config.CacheConfig.CACHE_TECHNICALS;

@Service
@Slf4j
public class TechnicalsService {

    public record TechnicalsData(
            List<IndicatorSnapshot> indicators,
            Double currentPrice,
            Double openPrice,
            Double changePct1d,
            Double changeOpenToClose,
            List<Double> sparkline
    ) {}

    private final RestClient genaiClient;
    private final ObjectMapper objectMapper;

    public TechnicalsService(@Qualifier("genaiRestClient") RestClient genaiClient,
                             ObjectMapper objectMapper) {
        this.genaiClient = genaiClient;
        this.objectMapper = objectMapper;
    }

    /**
     * 티커의 기술적 지표 + 현재가 + 등락률 + 스파크라인 반환.
     * GenAI 응답에 없는 필드는 null로 반환된다.
     */
    @Cacheable(value = CACHE_TECHNICALS, key = "#ticker")
    public TechnicalsData getTechnicals(String ticker) {
        try {
            String response = genaiClient.get()
                    .uri("/api/v1/technicals/{ticker}", ticker)
                    .retrieve()
                    .body(String.class);

            JsonNode root = objectMapper.readTree(response);
            List<IndicatorSnapshot> result = new ArrayList<>();

            if (root.has("RSI") && !root.get("RSI").isNull())
                result.add(parseRsi(root.get("RSI").asDouble()));

            if (root.has("MACD") && root.get("MACD").isObject())
                result.add(parseMacd(root.get("MACD")));

            if (root.has("BB") && root.get("BB").isObject())
                result.add(parseBollinger(root.get("BB")));

            if (root.has("volume_ratio") && !root.get("volume_ratio").isNull())
                result.add(parseVolume(root.get("volume_ratio").asDouble()));

            Double currentPrice = root.has("current_price") && !root.get("current_price").isNull()
                    ? root.get("current_price").asDouble() : null;
            Double openPrice = root.has("open_price") && !root.get("open_price").isNull()
                    ? root.get("open_price").asDouble() : null;
            Double changePct1d = root.has("change_pct_1d") && !root.get("change_pct_1d").isNull()
                    ? root.get("change_pct_1d").asDouble() : null;
            Double changeOpenToClose = root.has("change_open_to_close") && !root.get("change_open_to_close").isNull()
                    ? root.get("change_open_to_close").asDouble() : null;

            List<Double> sparkline = null;
            if (root.has("sparkline") && root.get("sparkline").isArray()) {
                sparkline = new ArrayList<>();
                for (JsonNode n : root.get("sparkline")) sparkline.add(n.asDouble());
            }

            return new TechnicalsData(result.isEmpty() ? null : result, currentPrice, openPrice, changePct1d, changeOpenToClose, sparkline);
        } catch (RestClientResponseException e) {
            log.warn("[기술적지표] {} HTTP {}: {}", ticker, e.getStatusCode().value(), e.getMessage());
            return null;
        } catch (Exception e) {
            log.warn("[기술적지표] {} 조회 실패: {}", ticker, e.getMessage());
            return null;
        }
    }

    private IndicatorSnapshot parseRsi(double rsi) {
        String label, captionSuffix;
        if (rsi >= 70) {
            label = "과열";
            captionSuffix = "단기 과매수 구간이에요.";
        } else if (rsi <= 30) {
            label = "과매도";
            captionSuffix = "저점 매수 관심 구간이에요.";
        } else {
            label = "중립";
            captionSuffix = "안정적인 구간이에요.";
        }
        return new IndicatorSnapshot(
                "RSI",
                rsi,
                null,
                label,
                String.format("RSI %.1f — %s", rsi, captionSuffix));
    }

    private IndicatorSnapshot parseMacd(JsonNode node) {
        double macd = node.path("macd").asDouble(0);
        double signal = node.path("signal").asDouble(0);
        String trend = node.path("trend").asText("");

        String displayText = switch (trend) {
            case "상승" -> "강세";
            case "하락" -> "약세";
            default -> macd > signal ? "강세" : "약세";
        };

        String crossType = node.path("signal_cross").asText("");
        String label;
        String caption;
        if ("golden".equalsIgnoreCase(crossType) || (macd > signal && Math.abs(macd - signal) < 0.5)) {
            label = "골든크로스";
            caption = "시그널선을 상향 돌파, 상승 모멘텀 강화.";
        } else if ("death".equalsIgnoreCase(crossType) || macd < signal) {
            label = "데드크로스";
            caption = "시그널선을 하향 돌파, 하락 압력 증가.";
        } else {
            label = "강세".equals(displayText) ? "상승추세" : "하락추세";
            caption = "MACD " + (macd >= 0 ? "양전환" : "음권") + " 구간.";
        }

        return new IndicatorSnapshot("MACD", null, displayText, label, caption);
    }

    private IndicatorSnapshot parseBollinger(JsonNode node) {
        String position = node.path("position").asText("");
        String displayText, label, caption;

        switch (position) {
            case "상단돌파" -> {
                displayText = "이탈";
                label = "상단 돌파";
                caption = "상단 밴드를 벗어나 변동성이 커졌어요.";
            }
            case "하단돌파" -> {
                displayText = "이탈";
                label = "하단 이탈";
                caption = "하단 밴드를 벗어나 과매도 가능성이 있어요.";
            }
            case "상단" -> {
                displayText = "상단";
                label = "상단 밴드";
                caption = "상단 밴드 근처 — 과열 주의 구간이에요.";
            }
            case "하단" -> {
                displayText = "하단";
                label = "하단 밴드";
                caption = "하단 밴드 근처 — 반등 가능성 구간이에요.";
            }
            default -> {
                displayText = "중립";
                label = "밴드 내";
                caption = "밴드 내 안정적인 구간이에요.";
            }
        }

        return new IndicatorSnapshot("볼린저밴드", null, displayText, label, caption);
    }

    private IndicatorSnapshot parseVolume(double ratio) {
        String label, caption;
        if (ratio >= 3.0) {
            label = "급등";
            caption = String.format("평소의 약 %.1f배, 매수세가 몰렸어요.", ratio);
        } else if (ratio >= 2.0) {
            label = "증가";
            caption = String.format("평소의 약 %.1f배, 거래가 활발해요.", ratio);
        } else if (ratio <= 0.5) {
            label = "급감";
            caption = String.format("평소의 %.0f%% 수준으로 거래가 위축됐어요.", ratio * 100);
        } else {
            label = "보통";
            caption = "평균 수준의 거래량이에요.";
        }
        return new IndicatorSnapshot("거래량", ratio, null, label, caption);
    }
}
