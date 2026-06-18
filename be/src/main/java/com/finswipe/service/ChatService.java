package com.finswipe.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.finswipe.domain.entity.ChatMessage;
import com.finswipe.domain.entity.NewsArticle;
import com.finswipe.domain.repository.ChatMessageRepository;
import com.finswipe.domain.repository.NewsArticleRepository;
import com.finswipe.dto.response.ChatMessageDto;
import com.finswipe.dto.response.TickerInfo;
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
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import java.util.stream.Collectors;

@Service
@Slf4j
public class ChatService {

    private final ChatMessageRepository chatRepo;
    private final JdbcTemplate jdbc;
    private final ObjectMapper objectMapper;
    private final RestClient genaiClient;
    private final NewsArticleRepository newsRepo;
    private final TechnicalsService technicalsService;
    private final TickerService tickerService;

    public ChatService(ChatMessageRepository chatRepo,
                       JdbcTemplate jdbc,
                       ObjectMapper objectMapper,
                       @Qualifier("genaiRestClient") RestClient genaiClient,
                       NewsArticleRepository newsRepo,
                       TechnicalsService technicalsService,
                       TickerService tickerService) {
        this.chatRepo = chatRepo;
        this.jdbc = jdbc;
        this.objectMapper = objectMapper;
        this.genaiClient = genaiClient;
        this.newsRepo = newsRepo;
        this.technicalsService = technicalsService;
        this.tickerService = tickerService;
    }

    // 이중 방어 — GenAI가 인젝션에 뚫려 프롬프트/탈옥 내용을 흘려도 백엔드에서 차단
    private static final String CHAT_REFUSAL =
            "해당 요청은 도와드릴 수 없어요. 시스템 내부 정보나 규칙은 공개할 수 없지만, 투자 정보 관련 질문이라면 기꺼이 도와드릴게요.";
    private static final List<String> LEAK_MARKERS = List.of(
            "jailbroken", "[유저 프로필]", "[답변 규칙]", "[설명 깊이]", "[분석 관점]",
            "[보안 규칙", "시스템 프롬프트", "system prompt", "개인화 금융 투자 ai 어시스턴트입니다");

    private static boolean leaksPrompt(String reply) {
        if (reply == null) return false;
        String low = reply.toLowerCase();
        return LEAK_MARKERS.stream().anyMatch(low::contains);
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

        // 캐시 인사이트 우선 — 종목 인사이트 질문은 LLM 토큰 없이 분석된 DB 데이터로 응답
        String aiContent = tryCachedInsight(userContent, tickers)
                .orElseGet(() -> callGenAiChat(userContent, history, level, tendency, tickers));

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
            if (leaksPrompt(reply)) {
                log.warn("[챗봇] 프롬프트 누출 의심 응답 차단 (output guard)");
                return CHAT_REFUSAL;
            }
            return reply;
        } catch (Exception e) {
            log.error("[챗봇] GenAI 응답 실패: {}", e.getMessage());
            return "죄송합니다, 지금은 응답할 수 없습니다. 잠시 후 다시 시도해주세요.";
        }
    }

    // ===================== 캐시 인사이트 라우터 (토큰 절감) =====================

    private static final List<String> INSIGHT_INTENT = List.of(
            "인사이트", "뉴스", "소식", "어때", "어떄", "전망", "동향", "현황", "분석", "오늘", "알려", "정보");

    private static boolean isInsightIntent(String msg) {
        return INSIGHT_INTENT.stream().anyMatch(msg::contains);
    }

    /**
     * 종목 인사이트 질문은 이미 분석된 DB 데이터로 응답 (LLM 토큰 0).
     * 관심 종목 → 최신 분석 기사 + 지표, 비관심 종목 → 정보 + 관심 종목 추가 CTA.
     * 처리 불가하면 empty 반환 → 호출부에서 LLM 폴백.
     */
    private Optional<String> tryCachedInsight(String message, List<String> watchlist) {
        try {
            if (!isInsightIntent(message)) return Optional.empty();
            List<TickerInfo> mentioned = tickerService.findMentionedTickers(message);
            if (mentioned.isEmpty()) return Optional.empty();

            Set<String> wl = watchlist == null ? Set.of()
                    : watchlist.stream()
                        .map(t -> t.replace("\"", "").strip().toUpperCase())
                        .filter(s -> !s.isEmpty())
                        .collect(Collectors.toSet());

            TickerInfo wlHit = mentioned.stream()
                    .filter(i -> wl.contains(i.getTicker()))
                    .findFirst().orElse(null);
            if (wlHit != null) {
                return buildWatchlistInsight(wlHit);   // 분석 기사 있으면 토큰0, 없으면 empty→LLM
            }
            return Optional.of(buildAddTickerCta(mentioned.get(0)));
        } catch (Exception e) {
            log.warn("[챗봇] 캐시 인사이트 분기 실패 — LLM 폴백: {}", e.getMessage());
            return Optional.empty();
        }
    }

    private Optional<String> buildWatchlistInsight(TickerInfo info) {
        String sym = info.getTicker();
        List<UUID> ids = newsRepo.findIdsByTickersOverlap("{" + sym + "}", 1, 0);
        if (ids == null || ids.isEmpty()) return Optional.empty();
        List<NewsArticle> articles = newsRepo.findByIdIn(ids);
        if (articles.isEmpty()) return Optional.empty();
        NewsArticle top = articles.get(0);

        String name = (info.getKo() != null && !info.getKo().isBlank()) ? info.getKo() : sym;
        StringBuilder sb = new StringBuilder();
        sb.append("📊 ").append(name).append("(").append(sym).append(") 인사이트\n");

        TechnicalsService.TechnicalsData td = null;
        try { td = technicalsService.getTechnicals(sym); } catch (Exception ignored) {}
        if (td != null && td.currentPrice() != null) {
            sb.append("현재가 $").append(String.format("%.2f", td.currentPrice()));
            if (td.changePct1d() != null) sb.append(String.format(" (%+.2f%%)", td.changePct1d()));
            sb.append("\n");
        }

        String hl = top.getHeadlineKo() != null ? top.getHeadlineKo() : top.getHeadline();
        sb.append("\n📰 최근 소식\n");
        if (hl != null) sb.append("• ").append(hl).append("\n");
        List<String> sum = top.getSummary3linesKo();
        if (sum != null) for (String line : sum) sb.append("  - ").append(line).append("\n");
        if (top.getSentimentLabel() != null) {
            sb.append("감성: ").append(sentimentKo(top.getSentimentLabel()));
            Double sc = top.getSentimentScore();
            if (sc != null) sb.append(String.format(" (%.0f)", sc * 100));
            sb.append("\n");
        }

        if (td != null && td.indicators() != null && !td.indicators().isEmpty()) {
            sb.append("\n📈 기술 지표\n");
            for (var ind : td.indicators()) {
                sb.append("• ").append(ind.type()).append(": ").append(ind.label());
                if (ind.caption() != null) sb.append(" — ").append(ind.caption());
                sb.append("\n");
            }
        }
        sb.append("\n※ 투자 권유가 아닌 정보 제공이에요.");
        return Optional.of(sb.toString().strip());
    }

    private String buildAddTickerCta(TickerInfo info) {
        String sym = info.getTicker();
        String name = (info.getKo() != null && !info.getKo().isBlank()) ? info.getKo() : sym;
        StringBuilder sb = new StringBuilder();
        sb.append(name).append("(").append(sym).append(")은(는) 아직 관심 종목에 없어요.\n");
        try {
            List<UUID> ids = newsRepo.findIdsByTickersOverlap("{" + sym + "}", 1, 0);
            if (ids != null && !ids.isEmpty()) {
                List<NewsArticle> articles = newsRepo.findByIdIn(ids);
                if (!articles.isEmpty()) {
                    NewsArticle top = articles.get(0);
                    String hl = top.getHeadlineKo() != null ? top.getHeadlineKo() : top.getHeadline();
                    if (hl != null) sb.append("📰 최신 소식: ").append(hl).append("\n");
                }
            }
        } catch (Exception ignored) {}
        sb.append("\n관심 종목에 추가하시겠어요? 추가하면 매일 인사이트 브리핑을 받아볼 수 있어요! 📈");
        return sb.toString();
    }

    private static String sentimentKo(String label) {
        return switch (label == null ? "" : label) {
            case "positive" -> "긍정";
            case "negative" -> "부정";
            case "neutral" -> "중립";
            case "mixed" -> "혼조";
            default -> label;
        };
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
