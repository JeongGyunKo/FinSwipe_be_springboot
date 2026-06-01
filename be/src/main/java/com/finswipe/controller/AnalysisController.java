package com.finswipe.controller;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.security.SecurityRequirement;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.client.RestClient;

import java.nio.charset.StandardCharsets;

@Tag(name = "Analysis", description = "LangGraph 기반 사용자 맞춤 분석 에이전트")
@SecurityRequirement(name = "bearerAuth")
@RestController
@RequestMapping("/analysis")
@Slf4j
public class AnalysisController {

    private final RestClient genaiClient;

    public AnalysisController(@Qualifier("genaiRestClient") RestClient genaiClient) {
        this.genaiClient = genaiClient;
    }

    /**
     * POST /analysis/personalized
     * LangGraph 에이전트 — 사용자 레벨/성향 기반 맞춤 분석
     * body: { article_title, article_text, tickers, sentiment_label, sentiment_score,
     *         sentiment_reason, user_level, user_tendency }
     */
    @Operation(summary = "맞춤 분석", description = "기사 감성 결과 + 사용자 레벨/성향으로 개인화된 분석 생성. yfinance RSI/MACD 포함.")
    @PostMapping("/personalized")
    public ResponseEntity<String> personalizedAnalysis(@RequestBody String body) {
        try {
            return genaiClient.post()
                    .uri("/api/v1/analysis/personalized")
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(body)
                    .exchange((req, res) -> {
                        byte[] bytes = res.getBody().readAllBytes();
                        String raw = bytes.length > 0 ? new String(bytes, StandardCharsets.UTF_8) : "{}";
                        return ResponseEntity.status(res.getStatusCode())
                                .contentType(MediaType.APPLICATION_JSON)
                                .body(raw);
                    });
        } catch (Exception e) {
            log.error("[에이전트 프록시] 실패: {}", e.getMessage());
            return ResponseEntity.internalServerError()
                    .contentType(MediaType.APPLICATION_JSON)
                    .body("{\"error\":\"분석 서버에 연결할 수 없습니다\"}");
        }
    }
}
