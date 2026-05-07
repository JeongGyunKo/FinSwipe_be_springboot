package com.finswipe.dto.request;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import lombok.Getter;

import java.util.List;

@Getter
public class AnalyzeRequest {

    @NotBlank
    @Size(max = 500)
    private String headline;

    @NotBlank
    private String sourceUrl;

    @NotBlank
    private String content;

    private List<String> tickers;
}
