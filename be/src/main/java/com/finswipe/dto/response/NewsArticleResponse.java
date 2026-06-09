package com.finswipe.dto.response;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import com.finswipe.domain.entity.NewsArticle;
import com.finswipe.util.HighlightUtil;
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
    /** summary3linesKo 각 줄의 강조 구간 [[start,end], ...] 목록 */
    private final List<List<int[]>> summaryHighlightRanges;
    private final String sentimentReason;
    /** sentimentReason 텍스트의 강조 구간 */
    private final List<int[]> sentimentReasonHighlightRanges;
    private final String eventCategory;
    private final Boolean sentimentDivergence;
    private final Double noveltyScore;
    @JsonProperty("is_read")
    private final boolean isRead;

    public NewsArticleResponse(NewsArticle article, List<Map<String, String>> tickerNames) {
        this(article, tickerNames, false);
    }

    public NewsArticleResponse(NewsArticle article, List<Map<String, String>> tickerNames, boolean isRead) {
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
        this.sentimentScore = article.getSentimentScore();
        this.isMixed = article.getIsMixed();
        this.headlineKo = article.getHeadlineKo();
        this.summary3linesKo = article.getSummary3linesKo();
        this.summaryHighlightRanges = HighlightUtil.computeRangesForLines(article.getSummary3linesKo());
        this.sentimentReason = article.getSentimentReason();
        this.sentimentReasonHighlightRanges = HighlightUtil.computeRanges(article.getSentimentReason());
        this.eventCategory = article.getEventCategory();
        this.sentimentDivergence = article.getSentimentDivergence();
        this.noveltyScore = article.getNoveltyScore();
        this.isRead = isRead;
    }
}
