package com.finswipe.dto.response;

import lombok.AllArgsConstructor;
import lombok.Getter;

import java.util.List;

@Getter
@AllArgsConstructor
public class NewsListResponse {

    private final long count;
    private final int offset;
    private final List<NewsArticleResponse> data;
}
