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
    private final com.finswipe.service.TickerTimelineService timelineService;

    public AnalysisController(@Qualifier("genaiRestClient") RestClient genaiClient,
                              com.finswipe.service.TickerTimelineService timelineService) {
        this.genaiClient = genaiClient;
        this.timelineService = timelineService;
    }

    /** 종목 멀티데이 이벤트 타임라인 — 미국 거래 세션(16:00 ET 마감) 단위. 사용자 앱(JWT). */
    @Operation(summary = "거래일별 이벤트 타임라인",
            description = "최근 N개 미국 거래 세션(16:00 ET 마감 기준)별 대표 뉴스·감성. 다이제스트 멀티데이 흐름용. ticker 필수, sessions 기본 5(1~10). "
                    + "응답 sessions는 과거→오늘 오름차순(마지막이 오늘자).")
    @ApiResponse(responseCode = "200", content = @Content(examples = @ExampleObject(value = """
            {
              "ticker": "NVDA",
              "sessions": [
                { "date": "2026-06-24", "label": "6/24", "count": 73, "sentiment": "neutral", "avgScore": -0.05,
                  "articles": [ { "headlineKo": "엔비디아 데이터센터 수요 둔화 우려", "sentimentLabel": "neutral", "sentimentScore": 0.12 } ] },
                { "date": "2026-06-25", "label": "6/25", "count": 11, "sentiment": "positive", "avgScore": 0.31,
                  "articles": [ { "headlineKo": "엔비디아 신규 칩 공개", "sentimentLabel": "positive", "sentimentScore": 0.64 } ] }
              ]
            }
            """)))
    @GetMapping("/ticker-timeline")
    public ResponseEntity<java.util.Map<String, Object>> tickerTimeline(
            @RequestParam String ticker,
            @RequestParam(defaultValue = "5") int sessions) {
        try {
            return ResponseEntity.ok(timelineService.getTimeline(ticker, sessions));
        } catch (IllegalArgumentException e) {
            return ResponseEntity.badRequest().body(java.util.Map.of("error", e.getMessage()));
        }
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

    @Operation(summary = "티커별 일일 다이제스트",
            description = "관심 티커 각각에 대해 어제 장 마감 이후 기사 전체를 종합 분석. 성향·레벨 맞춤 3단 요약(`sections`: 어제의_핵심/주가_반응/오늘_전망) + 대표 기사(`news_articles`, 최대 5건) + RSI/MACD 보조지표. "
                    + "`sections`는 뉴스 없음·생성 실패 시 null이며, 이 경우 한 덩어리 `summary`로 폴백한다.")
    @ApiResponse(responseCode = "200", content = @Content(examples = @ExampleObject(value = """
            {
              "digests": [
                {
                  "ticker": "AAPL",
                  "articles_count": 5,
                  "sentiment_overview": { "positive": 3, "negative": 1, "neutral": 1, "avg_score": 0.42 },
                  "summary": "어제 마감 이후 애플은 어닝서프라이즈를 기록했고, 시간외에서 +2% 반응했으며, 오늘은 가이던스 코멘트에 주목할 필요가 있습니다.",
                  "sections": {
                    "어제의_핵심": "어제 장 마감 후 애플이 시장 예상을 웃도는 분기 실적을 발표했습니다.",
                    "주가_반응": "실적 발표 직후 시간외에서 +2% 반응했고, RSI는 68로 과열 직전 구간입니다.",
                    "오늘_전망": "가치투자형 관점에서 오늘은 서비스 매출 가이던스 코멘트를 확인할 필요가 있습니다."
                  },
                  "news_articles": [
                    { "headline_ko": "애플, 분기 실적 어닝서프라이즈", "headline": "Apple beats Q3 estimates",
                      "sentiment_label": "positive", "sentiment_score": 0.78, "published_at": "2026-06-24T20:15:00Z" }
                  ],
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
              "generated_at": "2026-06-25T15:30:00Z"
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
