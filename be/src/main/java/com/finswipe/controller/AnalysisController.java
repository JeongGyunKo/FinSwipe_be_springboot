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

    @Operation(summary = "오늘의 top30 통합 브리핑",
            description = "카드 피드(관심종목 무관, 오늘 직전 미국장 마감 이후 절대값 파워 상위 30개)를 다 읽었을 때 보여주는 요약. "
                    + "종목별 카드가 아니라 하루치 시장을 한 편으로 종합한 `briefing`(오늘의_시장/핵심_이슈/오늘_체크포인트) + "
                    + "대표 종목 보조지표 `indicators`(|감성|합 상위 최대 8종목, RSI·MACD·볼린저·거래량·52주위치·sparkline) + "
                    + "대표 기사 `top_articles`(최대 10건). 레벨·성향 맞춤이며 (레벨,성향)별 캐시. "
                    + "`briefing`은 생성 실패 시 null이고 이때 한 덩어리 `summary`로 폴백. 오늘 뉴스가 없으면 articles_count=0 + message.")
    @ApiResponse(responseCode = "200", content = @Content(examples = @ExampleObject(value = """
            {
              "type": "feed_top30",
              "articles_count": 30,
              "sentiment_overview": { "positive": 14, "negative": 11, "neutral": 5, "avg_score": 0.12 },
              "briefing": {
                "오늘의_시장": "오늘은 반도체 강세와 금리 경계가 동시에 나타나며 시장이 혼조세를 보였어요.",
                "핵심_이슈": "엔비디아의 실적 서프라이즈가 반도체 전반을 끌어올렸고, 연준 위원의 매파적 발언이 상승폭을 제한했습니다.",
                "오늘_체크포인트": "모멘텀 관점에서 반도체 대형주의 거래량과 국채금리 흐름을 함께 보는 게 좋아요."
              },
              "summary": "오늘은 반도체 강세와 금리 경계가... / 엔비디아의 실적 서프라이즈가... / 모멘텀 관점에서...",
              "top_articles": [
                { "headline_ko": "엔비디아 실적 서프라이즈", "headline": "Nvidia beats estimates",
                  "sentiment_label": "positive", "sentiment_score": 0.91, "tickers": ["NVDA"], "published_at": "2026-07-01T20:15:00Z" }
              ],
              "indicators": [
                { "ticker": "NVDA", "current_price": 128.4, "change_pct_1d": 3.2, "change_pct_1m": 11.5,
                  "volume_ratio": 1.8, "RSI": 68.0, "RSI_signal": "중립",
                  "MACD": { "macd": 0.42, "signal": 0.31, "histogram": 0.11, "trend": "상승" } }
              ],
              "user_level": 3,
              "user_tendency": "모멘텀형 투자자",
              "generated_at": "2026-07-01T15:30:00Z"
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
