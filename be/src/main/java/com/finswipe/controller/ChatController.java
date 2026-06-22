package com.finswipe.controller;

import com.finswipe.dto.request.ChatMessageRequest;
import com.finswipe.dto.response.ChatMessageDto;
import com.finswipe.service.ChatRateLimiter;
import com.finswipe.service.ChatService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.media.Content;
import io.swagger.v3.oas.annotations.media.ExampleObject;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.security.SecurityRequirement;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;

import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.UUID;

@Tag(name = "Chat", description = "AI 챗봇 대화 및 감성 알림")
@SecurityRequirement(name = "bearerAuth")
@RestController
@RequestMapping("/chat")
@RequiredArgsConstructor
@Slf4j
public class ChatController {

    private final ChatService chatService;
    private final ChatRateLimiter rateLimiter;
    private final JdbcTemplate jdbc;

    @Operation(summary = "메시지 전송", description = "유저 메시지를 AI에게 전달하고 응답을 반환합니다. 대화는 DB에 저장되어 히스토리 조회 가능.")
    @ApiResponse(responseCode = "200", content = @Content(examples = @ExampleObject(value = """
            {
              "id": "550e8400-e29b-41d4-a716-446655440000",
              "role": "assistant",
              "content": "NVDA는 현재 AI 반도체 시장에서...",
              "ticker": null,
              "articleId": null,
              "createdAt": "2026-06-17T12:00:00Z"
            }
            """)))
    @PostMapping("/message")
    public ResponseEntity<?> sendMessage(Authentication auth,
                                         @RequestBody ChatMessageRequest req) {
        UUID userId = extractUserId(auth);
        if (userId == null) return ResponseEntity.status(401).body(Map.of("error", "인증이 필요합니다"));

        ChatRateLimiter.ProbeResult probe = rateLimiter.probe(userId);
        log.debug("[챗봇 레이트리밋] userId={} remaining={} allowed={}", userId, probe.remaining(), probe.allowed());
        if (!probe.allowed()) {
            return ResponseEntity.status(429)
                    .header("Retry-After", String.valueOf(probe.retryAfterSeconds()))
                    .header("X-RateLimit-Limit", String.valueOf(ChatRateLimiter.RPM))
                    .header("X-RateLimit-Remaining", "0")
                    .header("X-RateLimit-Reset", String.valueOf(probe.resetEpochSeconds()))
                    .body(Map.of("error", "요청이 너무 많습니다. 잠시 후 다시 시도해주세요."));
        }

        if (req.content() == null || req.content().isBlank())
            return ResponseEntity.badRequest().body(Map.of("error", "메시지를 입력하세요"));
        if (req.content().length() > ChatRateLimiter.MSG_MAX_CHARS)
            return ResponseEntity.badRequest().body(Map.of("error",
                    "메시지는 " + ChatRateLimiter.MSG_MAX_CHARS + "자 이하로 입력해주세요"));

        UserContext ctx = loadUserContext(userId);
        ChatMessageDto response = chatService.sendUserMessage(
                userId, req.content(), ctx.level(), ctx.tendency(), ctx.tickers());
        return ResponseEntity.ok()
                .header("X-RateLimit-Limit", String.valueOf(ChatRateLimiter.RPM))
                .header("X-RateLimit-Remaining", String.valueOf(probe.remaining()))
                .header("X-RateLimit-Reset", String.valueOf(probe.resetEpochSeconds()))
                .body(response);
    }

    @Operation(summary = "채팅 히스토리", description = "최근 채팅 메시지(대화 + 알림)를 반환합니다. 기본 50개. role: user(유저입력) | assistant(AI응답) | alert(감성알림). alert는 ticker·articleId 포함.")
    @ApiResponse(responseCode = "200", content = @Content(examples = @ExampleObject(value = """
            {
              "messages": [
                {
                  "id": "550e8400-e29b-41d4-a716-446655440000",
                  "role": "user",
                  "content": "NVDA 지금 사도 될까요?",
                  "ticker": null,
                  "articleId": null,
                  "createdAt": "2026-06-17T12:01:00Z"
                },
                {
                  "id": "661e8400-e29b-41d4-a716-446655440001",
                  "role": "assistant",
                  "content": "NVDA는 현재 AI 반도체 시장에서...",
                  "ticker": null,
                  "articleId": null,
                  "createdAt": "2026-06-17T12:01:03Z"
                },
                {
                  "id": "772e8400-e29b-41d4-a716-446655440002",
                  "role": "alert",
                  "content": "📈 NVDA 긍정 신호\\n\\nNVIDIA 2분기 매출 예상치 상회...",
                  "ticker": "NVDA",
                  "articleId": "883e8400-e29b-41d4-a716-446655440003",
                  "createdAt": "2026-06-17T11:30:00Z"
                }
              ]
            }
            """)))
    @GetMapping("/messages")
    public ResponseEntity<?> getMessages(Authentication auth,
                                         @RequestParam(defaultValue = "50") int limit) {
        UUID userId = extractUserId(auth);
        if (userId == null) return ResponseEntity.status(401).body(Map.of("error", "인증이 필요합니다"));

        ChatRateLimiter.ProbeResult probe = rateLimiter.peek(userId);
        List<ChatMessageDto> messages = chatService.getHistory(userId, limit);
        return ResponseEntity.ok()
                .header("X-RateLimit-Limit", String.valueOf(ChatRateLimiter.RPM))
                .header("X-RateLimit-Remaining", String.valueOf(probe.remaining()))
                .header("X-RateLimit-Reset", String.valueOf(probe.resetEpochSeconds()))
                .body(Map.of("messages", messages));
    }

    private UUID extractUserId(Authentication auth) {
        if (auth == null) return null;
        Object principal = auth.getPrincipal();
        if (principal instanceof UUID uuid) return uuid;
        try { return UUID.fromString(principal.toString()); } catch (Exception e) { return null; }
    }

    private UserContext loadUserContext(UUID userId) {
        try {
            return jdbc.queryForObject(
                    "SELECT level, tendency, tickers FROM user_profiles WHERE id = CAST(? AS UUID)",
                    (rs, row) -> {
                        int level = rs.getInt("level");
                        String tendency = rs.getString("tendency");
                        String rawTickers = rs.getString("tickers");
                        List<String> tickers = rawTickers == null ? List.of()
                                : Arrays.asList(rawTickers.replaceAll("[{}]", "").split(","));
                        return new UserContext(level, tendency, tickers);
                    },
                    userId.toString());
        } catch (Exception e) {
            log.warn("[챗봇] 유저 컨텍스트 조회 실패: {}", e.getMessage());
            return new UserContext(1, null, List.of());
        }
    }

    private record UserContext(int level, String tendency, List<String> tickers) {}
}
