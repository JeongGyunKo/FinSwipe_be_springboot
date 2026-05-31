package com.finswipe.controller;

import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.client.RestClient;

import java.nio.charset.StandardCharsets;

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
