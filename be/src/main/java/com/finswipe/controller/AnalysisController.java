package com.finswipe.controller;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.media.Content;
import io.swagger.v3.oas.annotations.media.ExampleObject;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.security.SecurityRequirement;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.security.core.Authentication;
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
    @ApiResponse(responseCode = "200", content = @Content(examples = @ExampleObject(value = """
            {
              "personalized_analysis": "애플의 이번 분기 실적은 긍정적입니다. RSI가 72로 과매수 구간이나, MACD는 상승 추세를 보이고 있습니다.",
              "technical_indicators": {
                "AAPL": {
                  "RSI": 72.1,
                  "MACD": { "macd": 2.34, "signal": 1.89, "histogram": 0.45, "trend": "상승" },
                  "current_price": 195.5,
                  "change_pct_1m": 8.2
                }
              },
              "user_level": 3,
              "user_tendency": "가치투자형"
            }
            """)))
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

    @Operation(summary = "뉴스 큐레이션", description = "관심 티커·투자 성향 기반 오늘의 중요 뉴스 3개 선별")
    @ApiResponse(responseCode = "200", content = @Content(examples = @ExampleObject(value = """
            {
              "articles": [
                { "rank": 1, "article_id": "uuid", "headline_ko": "엔비디아 실적 어닝서프라이즈",
                  "reason": "보유 종목의 강한 상승 시그널로 즉각적인 확인이 필요합니다.",
                  "sentiment": "positive", "sentiment_score": 0.87, "tickers": ["NVDA"] }
              ],
              "tickers": ["NVDA", "AAPL"],
              "tendency": "모멘텀형"
            }
            """)))
    @PostMapping("/curate")
    public ResponseEntity<String> curate(Authentication auth, @RequestParam(required = false) String userId) {
        final String uid = resolveUserId(auth, userId);
        if (uid == null) return ResponseEntity.badRequest()
                .contentType(MediaType.APPLICATION_JSON).body("{\"error\":\"userId 필요\"}");
        if (!isValidUuid(uid)) return ResponseEntity.badRequest()
                .contentType(MediaType.APPLICATION_JSON).body("{\"error\":\"유효하지 않은 userId\"}");
        return proxy("/api/v1/analysis/curate", "{\"user_id\":\"" + uid + "\"}");
    }

    @Operation(summary = "티커별 일일 다이제스트", description = "관심 티커 각각에 대해 어제 장 마감 이후 기사 전체를 종합 분석 — 성향·레벨 맞춤 요약 + RSI/MACD 보조지표 반환")
    @ApiResponse(responseCode = "200", content = @Content(examples = @ExampleObject(value = """
            {
              "digests": [
                {
                  "ticker": "AAPL",
                  "articles_count": 5,
                  "sentiment_overview": { "positive": 3, "negative": 1, "neutral": 1, "avg_score": 0.42 },
                  "summary": "오늘 AAPL은 어닝서프라이즈를 기록하며 긍정적인 흐름을 보였습니다...",
                  "technical_indicators": {
                    "current_price": 194.5,
                    "change_pct_1d": 2.1,
                    "change_pct_1m": 8.2,
                    "volume_ratio": 1.35,
                    "RSI": 68.0,
                    "RSI_signal": "중립",
                    "MACD": { "macd": 0.42, "signal": 0.31, "histogram": 0.11, "trend": "상승" }
                  }
                }
              ],
              "user_level": 3,
              "user_tendency": "모멘텀형 투자자",
              "generated_at": "2024-07-26T15:30:00Z"
            }
            """)))
    @PostMapping("/digest")
    public ResponseEntity<String> digest(Authentication auth, @RequestParam(required = false) String userId) {
        final String uid = resolveUserId(auth, userId);
        if (uid == null) return ResponseEntity.badRequest()
                .contentType(MediaType.APPLICATION_JSON).body("{\"error\":\"userId 필요\"}");
        if (!isValidUuid(uid)) return ResponseEntity.badRequest()
                .contentType(MediaType.APPLICATION_JSON).body("{\"error\":\"유효하지 않은 userId\"}");
        return proxy("/api/v1/analysis/digest", "{\"user_id\":\"" + uid + "\"}");
    }

    @Operation(summary = "학습 코치", description = "퀴즈 영역별 점수 분석 → 강점·약점 파악 및 맞춤 학습 방향 제시")
    @ApiResponse(responseCode = "200", content = @Content(examples = @ExampleObject(value = """
            {
              "coaching": "기본개념과 매크로 영역에서 탁월한 실력을 보여주셨습니다!...",
              "area_stats": { "기본개념": { "score": 5.0, "correct": 2, "total": 2 } },
              "weak_areas": ["리스크관리", "펀더멘털"],
              "tendency": "가치투자형",
              "sessions_analyzed": 2
            }
            """)))
    @PostMapping("/coach")
    public ResponseEntity<String> coach(Authentication auth, @RequestParam(required = false) String userId) {
        final String uid = resolveUserId(auth, userId);
        if (uid == null) return ResponseEntity.badRequest()
                .contentType(MediaType.APPLICATION_JSON).body("{\"error\":\"userId 필요\"}");
        if (!isValidUuid(uid)) return ResponseEntity.badRequest()
                .contentType(MediaType.APPLICATION_JSON).body("{\"error\":\"유효하지 않은 userId\"}");
        return proxy("/api/v1/analysis/coach", "{\"user_id\":\"" + uid + "\"}");
    }

    private String resolveUserId(Authentication auth, String userId) {
        if (auth != null && auth.getPrincipal() instanceof java.util.UUID) return auth.getPrincipal().toString();
        return userId;
    }

    private static boolean isValidUuid(String value) {
        try { java.util.UUID.fromString(value); return true; }
        catch (IllegalArgumentException e) { return false; }
    }

    private ResponseEntity<String> proxy(String path, String body) {
        try {
            return genaiClient.post()
                    .uri(path)
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
