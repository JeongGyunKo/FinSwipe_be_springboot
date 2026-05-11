package com.finswipe.service;

import org.junit.jupiter.api.Test;

import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class NewsCollectorServiceTest {

    private final NewsCollectorService service = createService();

    @Test
    void filterTickers_removesNonUsTickers() {
        List<String> result = service.filterTickers(List.of("AAPL", "MSFT", "BTC", "ETH"));
        assertThat(result).containsExactlyInAnyOrder("AAPL", "MSFT");
        assertThat(result).doesNotContain("BTC", "ETH");
    }

    @Test
    void filterTickers_removesInvalidSuffixes() {
        List<String> result = service.filterTickers(List.of("AAPLW", "AAPLZ", "AAPL", "MSFTU"));
        assertThat(result).containsExactly("AAPL");
    }

    @Test
    void filterTickers_removesNonAlphaOnly() {
        List<String> result = service.filterTickers(List.of("AAPL", "AA1PL", "00XX"));
        assertThat(result).containsExactly("AAPL");
    }

    @Test
    void filterTickers_handlesNullAndEmpty() {
        assertThat(service.filterTickers(null)).isEmpty();
        assertThat(service.filterTickers(List.of())).isEmpty();
    }

    @Test
    void filterTickers_deduplicates() {
        List<String> result = service.filterTickers(List.of("AAPL", "aapl", "AAPL"));
        assertThat(result).hasSize(1).containsExactly("AAPL");
    }

    private NewsCollectorService createService() {
        // null 주입 — filterTickers()는 외부 의존성 없이 동작
        return new NewsCollectorService(null, null, null, null, null, null);
    }
}
