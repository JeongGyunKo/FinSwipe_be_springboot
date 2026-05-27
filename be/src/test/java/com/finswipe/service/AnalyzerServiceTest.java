package com.finswipe.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.finswipe.config.AppProperties;
import com.finswipe.domain.entity.NewsArticle;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class AnalyzerServiceTest {

    private AnalyzerService service;

    @BeforeEach
    void setUp() {
        // AppProperties 기본값(concurrentRequests=3)으로 Semaphore 초기화
        service = new AnalyzerService(null, null, null, new ObjectMapper(), new AppProperties());
    }

    @Test
    void enrichmentResult_unavailable_hasCorrectLabel() {
        AnalyzerService.EnrichmentResult result = AnalyzerService.EnrichmentResult.unavailable("http://example.com");
        assertThat(result.getSentimentLabel()).isEqualTo("unavailable");
        assertThat(result.isAvailable()).isFalse();
    }

    @Test
    void enrichSingle_handlesNullContent() {
        // GenAI client is null, so RestClientException is expected
        NewsArticle article = new NewsArticle();
        article.setHeadline("Test headline");
        article.setSourceUrl("http://example.com/article");
        article.setContent(null);

        // null client → NullPointerException caught → returns unavailable
        AnalyzerService.EnrichmentResult result = service.enrichSingle(article);
        assertThat(result.isAvailable()).isFalse();
    }
}
