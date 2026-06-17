package com.finswipe.dto.response;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.finswipe.domain.entity.NewsArticle;
import lombok.Getter;

import java.time.OffsetDateTime;
import java.util.List;
import java.util.Map;
import java.util.UUID;

@Getter
@JsonInclude(JsonInclude.Include.NON_NULL)
public class NewsArticleResponse {

    private final UUID id;
    private final String headline;
    private final List<String> summary3lines;
    private final String sourceUrl;
    private final String contentPreview;
    private final String imageUrl;
    private final OffsetDateTime publishedAt;
    private final List<String> categories;
    private final List<String> countries;
    private final List<String> tickers;
    private final List<Map<String, String>> tickerNames;
    private final boolean isPaywalled;
    private final String sentimentLabel;
    private final Double sentimentScore;
    private final Boolean isMixed;
    private final String headlineKo;
    private final List<String> summary3linesKo;
    private final String sentimentReason;
    private final String eventCategory;
    private final Boolean sentimentDivergence;
    private final Double noveltyScore;
    @JsonProperty("is_read")
    private final boolean isRead;
    private final List<IndicatorSnapshot> indicators;
    private final Double currentPrice;
    private final Double changePct1d;
    private final List<Double> sparkline;

    /**
     * type: RSI | MACD | 볼린저밴드 | 거래량
     * value: 숫자 주 표시값 (RSI: 74.2, 거래량 배율: 3.5) — null이면 displayText 사용
     * displayText: 텍스트 주 표시값 (MACD: "강세", 볼린저: "이탈") — null이면 value 사용
     * label: 배지 태그 (과열, 골든크로스, 상단 돌파, 급등)
     * caption: 설명 문구
     */
    public record IndicatorSnapshot(String type, Double value, String displayText, String label, String caption) {}

    public NewsArticleResponse(NewsArticle article, List<Map<String, String>> tickerNames) {
        this(article, tickerNames, false, null, null, null, null);
    }

    public NewsArticleResponse(NewsArticle article, List<Map<String, String>> tickerNames, boolean isRead) {
        this(article, tickerNames, isRead, null, null, null, null);
    }

    public NewsArticleResponse(NewsArticle article, List<Map<String, String>> tickerNames, boolean isRead, List<IndicatorSnapshot> indicators) {
        this(article, tickerNames, isRead, indicators, null, null, null);
    }

    public NewsArticleResponse(NewsArticle article, List<Map<String, String>> tickerNames, boolean isRead,
                               List<IndicatorSnapshot> indicators, Double currentPrice, Double changePct1d, List<Double> sparkline) {
        this.id = article.getId();
        this.headline = article.getHeadline();
        this.summary3lines = article.getSummary3lines();
        this.sourceUrl = article.getSourceUrl();
        this.contentPreview = article.getContentPreview();
        this.imageUrl = article.getImageUrl();
        this.publishedAt = article.getPublishedAt();
        this.categories = article.getCategories();
        this.countries = article.getCountries();
        this.tickers = article.getTickers();
        this.tickerNames = tickerNames;
        this.isPaywalled = article.isPaywalled();
        this.sentimentLabel = article.getSentimentLabel();
        Double raw = article.getSentimentScore();
        this.sentimentScore = raw != null ? Math.round(raw * 1000.0) / 10.0 : null;
        this.isMixed = article.getIsMixed();
        this.headlineKo = article.getHeadlineKo();
        this.summary3linesKo = article.getSummary3linesKo();
        this.sentimentReason = article.getSentimentReason();
        this.eventCategory = article.getEventCategory();
        this.sentimentDivergence = article.getSentimentDivergence();
        this.noveltyScore = article.getNoveltyScore();
        this.isRead = isRead;
        this.indicators = indicators;
        this.currentPrice = currentPrice;
        this.changePct1d = changePct1d;
        this.sparkline = sparkline;
    }
}
