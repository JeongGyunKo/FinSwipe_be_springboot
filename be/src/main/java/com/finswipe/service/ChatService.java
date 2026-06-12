package com.finswipe.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.finswipe.domain.entity.ChatMessage;
import com.finswipe.domain.entity.NewsArticle;
import com.finswipe.domain.repository.ChatMessageRepository;
import com.finswipe.dto.response.ChatMessageDto;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.data.domain.PageRequest;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;

import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

@Service
@Slf4j
public class ChatService {

    private final ChatMessageRepository chatRepo;
    private final JdbcTemplate jdbc;
    private final ObjectMapper objectMapper;
    private final RestClient genaiClient;

    public ChatService(ChatMessageRepository chatRepo,
                       JdbcTemplate jdbc,
                       ObjectMapper objectMapper,
                       @Qualifier("genaiRestClient") RestClient genaiClient) {
        this.chatRepo = chatRepo;
        this.jdbc = jdbc;
        this.objectMapper = objectMapper;
        this.genaiClient = genaiClient;
    }

    /**
     * 유저 메시지를 GenAI로 전달하고 응답을 저장 후 반환.
     * history는 최근 10개 대화(알림 제외)를 컨텍스트로 전달한다.
     */
    public ChatMessageDto sendUserMessage(UUID userId, String userContent,
                                          int level, String tendency, List<String> tickers) {
        // 유저 메시지 저장
        ChatMessage userMsg = new ChatMessage();
        userMsg.setUserId(userId);
        userMsg.setRole("user");
        userMsg.setContent(userContent);
        chatRepo.save(userMsg);

        // 직전 10개 대화 (알림 제외) — 오래된 순으로 뒤집어 GenAI에 전달
        List<Map<String, String>> history = chatRepo
                .findRecentByUserId(userId, PageRequest.of(0, 10))
                .stream()
                .filter(m -> !"alert".equals(m.getRole()))
                .map(m -> Map.of("role", m.getRole(), "content", m.getContent()))
                .toList()
                .reversed();

        String aiContent = callGenAiChat(userContent, history, level, tendency, tickers);

        ChatMessage assistantMsg = new ChatMessage();
        assistantMsg.setUserId(userId);
        assistantMsg.setRole("assistant");
        assistantMsg.setContent(aiContent);
        chatRepo.save(assistantMsg);

        return toDto(assistantMsg);
    }

    /** 채팅 히스토리 최근 limit개 — 최신순 반환 */
    public List<ChatMessageDto> getHistory(UUID userId, int limit) {
        return chatRepo.findRecentByUserId(userId, PageRequest.of(0, Math.min(limit, 100)))
                .stream()
                .map(this::toDto)
                .toList();
    }

    /**
     * 기사 분석 완료 후 호출: 구독 유저에게 챗 알림 메시지 생성.
     * notify_sentiment_news = true 인 유저만 대상.
     */
    public void dispatchRecommendationAlerts(NewsArticle article, List<String> tickers) {
        if (tickers == null || tickers.isEmpty()) return;

        String tickerArray = "{" + String.join(",", tickers) + "}";
        List<UUID> userIds;
        try {
            userIds = jdbc.queryForList(
                    "SELECT id FROM user_profiles WHERE tickers && ?::text[] AND notify_sentiment_news = true",
                    UUID.class, tickerArray);
        } catch (Exception e) {
            log.error("[챗봇 알림] 구독 유저 조회 실패: {}", e.getMessage());
            return;
        }
        if (userIds.isEmpty()) return;

        String content = buildAlertContent(article, tickers);
        String tickerStr = String.join(",", tickers);

        List<ChatMessage> alerts = userIds.stream().map(uid -> {
            ChatMessage alert = new ChatMessage();
            alert.setUserId(uid);
            alert.setRole("alert");
            alert.setContent(content);
            alert.setTicker(tickerStr);
            alert.setArticleId(article.getId());
            return alert;
        }).toList();

        chatRepo.saveAll(alerts);
        log.info("[챗봇 알림] {}개 유저에게 감성 알림 저장 ({})", userIds.size(), tickerStr);
    }

    private String callGenAiChat(String message, List<Map<String, String>> history,
                                  int level, String tendency, List<String> tickers) {
        try {
            Map<String, Object> body = new HashMap<>();
            body.put("message", message);
            body.put("history", history);
            body.put("user_level", level);
            body.put("user_tendency", tendency != null ? tendency : "");
            body.put("user_tickers", tickers != null ? tickers : List.of());

            String raw = genaiClient.post()
                    .uri("/api/v1/chat/message")
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(objectMapper.writeValueAsString(body))
                    .exchange((req, res) -> {
                        byte[] bytes = res.getBody().readAllBytes();
                        return bytes.length > 0 ? new String(bytes, StandardCharsets.UTF_8) : "{}";
                    });

            JsonNode node = objectMapper.readTree(raw);
            // GenAI 응답 필드: reply 또는 message
            String reply = node.path("reply").asText(null);
            if (reply == null || reply.isBlank()) reply = node.path("message").asText(null);
            if (reply == null || reply.isBlank()) return "응답을 받아오지 못했습니다.";
            return reply;
        } catch (Exception e) {
            log.error("[챗봇] GenAI 응답 실패: {}", e.getMessage());
            return "죄송합니다, 지금은 응답할 수 없습니다. 잠시 후 다시 시도해주세요.";
        }
    }

    private String buildAlertContent(NewsArticle article, List<String> tickers) {
        String label = article.getSentimentLabel();
        Double score = article.getSentimentScore();
        boolean isPositive = "positive".equals(label);
        boolean isNegative = "negative".equals(label);

        String emoji = isPositive ? "📈" : isNegative ? "📉" : "📊";
        String signal = isPositive ? "긍정 신호" : isNegative ? "주의 신호" : "주목할 뉴스";
        String tickerLabel = String.join(" · ", tickers.subList(0, Math.min(3, tickers.size())));

        StringBuilder sb = new StringBuilder();
        sb.append(emoji).append(" ").append(tickerLabel).append(" ").append(signal).append("\n\n");

        String headline = article.getHeadlineKo() != null ? article.getHeadlineKo() : article.getHeadline();
        if (headline != null) sb.append(headline).append("\n\n");

        List<String> summaryKo = article.getSummary3linesKo();
        if (summaryKo != null && !summaryKo.isEmpty()) {
            for (String line : summaryKo) sb.append("• ").append(line).append("\n");
            sb.append("\n");
        }

        if (score != null) sb.append("감성 점수: ").append(String.format("%.2f", score));

        if (isPositive) sb.append("\n→ 포트폴리오 편입을 고려해볼 시점일 수 있습니다.");
        else if (isNegative) sb.append("\n→ 단기 리스크 관리가 필요할 수 있습니다.");

        return sb.toString();
    }

    private ChatMessageDto toDto(ChatMessage m) {
        return new ChatMessageDto(
                m.getId(), m.getRole(), m.getContent(),
                m.getTicker(), m.getArticleId(), m.getCreatedAt());
    }
}
