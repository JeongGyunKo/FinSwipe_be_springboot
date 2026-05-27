package com.finswipe.dto.response;

import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.Getter;

import java.util.List;

@Getter
@JsonInclude(JsonInclude.Include.NON_NULL)
public class NewsListResponse {

    private final long count;
    private final int offset;
    private final List<NewsArticleResponse> data;
    private final List<String> userTickers;  // userId 경로에서만 포함

    public NewsListResponse(long count, int offset, List<NewsArticleResponse> data) {
        this.count = count;
        this.offset = offset;
        this.data = data;
        this.userTickers = null;
    }

    public NewsListResponse(long count, int offset, List<NewsArticleResponse> data, List<String> userTickers) {
        this.count = count;
        this.offset = offset;
        this.data = data;
        this.userTickers = userTickers;
    }
}
