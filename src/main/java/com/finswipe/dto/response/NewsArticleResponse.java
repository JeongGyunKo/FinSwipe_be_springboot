package com.finswipe.dto.response;

import com.fasterxml.jackson.annotation.JsonInclude;
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
    private final String summary;
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
    private final String xai;
    private final Boolean isMixed;
    private final String headlineKo;
    private final List<String> summary3linesKo;
    private final String xaiKo;

    public NewsArticleResponse(NewsArticle article, List<Map<String, String>> tickerNames) {
        this.id = article.getId();
        this.headline = article.getHeadline();
        this.summary = article.getSummary();
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
        this.sentimentScore = article.getSentimentScore();
        this.xai = article.getXai();
        this.isMixed = article.getIsMixed();
        this.headlineKo = article.getHeadlineKo();
        this.summary3linesKo = article.getSummary3linesKo();
        this.xaiKo = article.getXaiKo();
    }
}
