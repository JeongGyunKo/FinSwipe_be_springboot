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
    @Size(max = 2048)
    private String sourceUrl;

    @NotBlank
    @Size(max = 100_000)
    private String content;

    @Size(max = 50)
    private List<String> tickers;
}
