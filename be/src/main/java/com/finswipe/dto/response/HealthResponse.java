package com.finswipe.dto.response;

import lombok.AllArgsConstructor;
import lombok.Getter;

@Getter
@AllArgsConstructor
public class HealthResponse {

    private final String status;
    private final String db;
    private final String genai;
}
