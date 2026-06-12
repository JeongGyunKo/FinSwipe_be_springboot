package com.finswipe.controller;

import com.finswipe.dto.request.ChatMessageRequest;
import com.finswipe.dto.response.ChatMessageDto;
import com.finswipe.service.ChatService;
import io.swagger.v3.oas.annotations.Operation;
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
    private final JdbcTemplate jdbc;

    @Operation(summary = "메시지 전송", description = "유저 메시지를 AI에게 전달하고 응답을 반환합니다.")
    @PostMapping("/message")
    public ResponseEntity<?> sendMessage(Authentication auth,
                                         @RequestBody ChatMessageRequest req) {
        UUID userId = extractUserId(auth);
        if (userId == null) return ResponseEntity.status(401).body(Map.of("error", "인증이 필요합니다"));
        if (req.content() == null || req.content().isBlank())
            return ResponseEntity.badRequest().body(Map.of("error", "메시지를 입력하세요"));

        UserContext ctx = loadUserContext(userId);
        ChatMessageDto response = chatService.sendUserMessage(
                userId, req.content(), ctx.level(), ctx.tendency(), ctx.tickers());
        return ResponseEntity.ok(response);
    }

    @Operation(summary = "채팅 히스토리", description = "최근 채팅 메시지(대화 + 알림)를 반환합니다. 기본 50개.")
    @GetMapping("/messages")
    public ResponseEntity<?> getMessages(Authentication auth,
                                         @RequestParam(defaultValue = "50") int limit) {
        UUID userId = extractUserId(auth);
        if (userId == null) return ResponseEntity.status(401).body(Map.of("error", "인증이 필요합니다"));

        List<ChatMessageDto> messages = chatService.getHistory(userId, limit);
        return ResponseEntity.ok(Map.of("messages", messages));
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
