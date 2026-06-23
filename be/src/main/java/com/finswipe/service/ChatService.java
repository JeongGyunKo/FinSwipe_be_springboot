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
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import java.util.regex.Pattern;
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
    private static final String PRICE_UNAVAILABLE =
            "해당 종목의 주가 데이터를 가져올 수 없어요. 데이터 소스에 아직 없거나 일시적으로 조회가 어려울 수 있어요.";
    private static final List<String> LEAK_MARKERS = List.of(
            "jailbroken", "[유저 프로필]", "[답변 규칙]", "[설명 깊이]", "[분석 관점]",
            "[보안 규칙", "시스템 프롬프트", "system prompt", "개인화 금융 투자 ai 어시스턴트입니다");
    private static final Pattern PLACEHOLDER_RE = Pattern.compile(
            "\\[[^\\]\\n]{2,80}(?:삽입|insert|정보|가격|시세|데이터|값|price|information|here)[^\\]\\n]{0,20}\\]",
            Pattern.CASE_INSENSITIVE);
    private static final List<String> PRICE_KEYWORDS = List.of(
            "주가", "가격", "얼마", "price", "시세", "현재가", "종가", "시가", "고가", "저가");

    private static boolean leaksPrompt(String reply) {
        if (reply == null) return false;
        String low = reply.toLowerCase();
        return LEAK_MARKERS.stream().anyMatch(low::contains);
    }

    private static String sanitizePlaceholders(String reply) {
        if (reply == null) return reply;
        return PLACEHOLDER_RE.matcher(reply).replaceAll(PRICE_UNAVAILABLE);
    }

    private static boolean isPriceQuery(String message) {
        String lower = message.toLowerCase();
        return PRICE_KEYWORDS.stream().anyMatch(lower::contains);
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
        userMsg.setRead(true);
        chatRepo.save(userMsg);

        // 직전 10개 대화 (알림 제외) — 오래된 순으로 뒤집어 GenAI에 전달
        List<Map<String, String>> history = chatRepo
                .findRecentByUserId(userId, PageRequest.of(0, 10))
                .stream()
                .filter(m -> !"alert".equals(m.getRole()))
                .map(m -> Map.of("role", m.getRole(), "content", m.getContent()))
                .toList()
                .reversed();

        // 가격 질문이면 현재가 조회, 아니면 상장 확인 정보만 전달 (LLM이 "비상장" 오답 방지)
        PriceResult priceResult = isPriceQuery(userContent)
                ? buildTickerPrices(userContent)
                : buildListedTickersOnly(userContent);

        // 상장폐지 예정 종목 언급 시 즉시 안내 (인사이트 여부 무관)
        String delistingNotice = buildDelistingNotice(userContent);

        // 워치리스트 질문("내 관심종목 뭐야") → DB 워치리스트 직접 응답 (LLM 토큰 0)
        // 그 외 종목 인사이트 질문 → 분석된 DB 데이터로 응답 (LLM 토큰 0)
        String aiContent = tryWatchlistAnswer(userContent, tickers)
                .or(() -> tryCachedInsight(userContent, tickers)
                        .map(insight -> delistingNotice != null ? delistingNotice + "\n\n" + insight : insight))
                .orElseGet(() -> {
                    // 가격 질문인데 언급 종목이 전부 조회 불가(상장폐지 등)인 경우 LLM 차단
                    // — Gemini가 학습 데이터 가격을 할루시네이션하는 것을 사전에 막기 위함
                    if (isPriceQuery(userContent)
                            && priceResult.available().isEmpty()
                            && !priceResult.unavailable().isEmpty()) {
                        String names = String.join(", ", priceResult.unavailable());
                        return names + "의 주가 데이터를 가져올 수 없어요. 데이터 소스에 아직 없거나 일시적으로 조회가 어려울 수 있어요.";
                    }
                    String llmReply = callGenAiChat(userContent, history, level, tendency, tickers, priceResult);
                    return delistingNotice != null ? delistingNotice + "\n\n" + llmReply : llmReply;
                });

        ChatMessage assistantMsg = new ChatMessage();
        assistantMsg.setUserId(userId);
        assistantMsg.setRole("assistant");
        assistantMsg.setContent(aiContent);
        assistantMsg.setRead(false);
        chatRepo.save(assistantMsg);

        return toDto(assistantMsg);
    }

    /** 미읽음 감성 알림 개수 — "N개의 주요한 뉴스가 있어요" 안내·뱃지용 */
    public long countUnreadAlerts(UUID userId) {
        return chatRepo.countUnreadAlerts(userId);
    }

    /** 채팅 히스토리 최근 limit개 — 최신순 반환, 조회 시 미읽음 메시지 읽음 처리 */
    @org.springframework.transaction.annotation.Transactional
    public List<ChatMessageDto> getHistory(UUID userId, int limit) {
        List<ChatMessageDto> messages = chatRepo.findRecentByUserId(userId, PageRequest.of(0, Math.min(limit, 100)))
                .stream()
                .map(this::toDto)
                .toList();
        chatRepo.markAllReadByUserId(userId);
        return messages;
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
            alert.setRead(false);
            return alert;
        }).toList();

        chatRepo.saveAll(alerts);
        log.info("[챗봇 알림] {}개 유저에게 감성 알림 저장 ({})", userIds.size(), tickerStr);
    }

    private String callGenAiChat(String message, List<Map<String, String>> history,
                                  int level, String tendency, List<String> tickers,
                                  PriceResult priceResult) {
        try {
            Map<String, Object> body = new HashMap<>();
            body.put("message", message);
            body.put("history", history);
            body.put("user_level", level);
            body.put("user_tendency", tendency != null ? tendency : "");
            body.put("user_tickers", tickers != null ? tickers : List.of());
            body.put("ticker_prices", priceResult.available());
            body.put("unavailable_tickers", priceResult.unavailable());

            String raw = genaiClient.post()
                    .uri("/api/v1/chat/message")
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(objectMapper.writeValueAsString(body))
                    .exchange((req, res) -> {
                        byte[] bytes = res.getBody().readAllBytes();
                        return bytes.length > 0 ? new String(bytes, StandardCharsets.UTF_8) : "{}";
                    });

            JsonNode node = objectMapper.readTree(raw);
            String reply = node.path("reply").asText(null);
            if (reply == null || reply.isBlank()) reply = node.path("message").asText(null);
            if (reply == null || reply.isBlank()) return "응답을 받아오지 못했습니다.";
            if (leaksPrompt(reply)) {
                log.warn("[챗봇] 프롬프트 누출 의심 응답 차단 (output guard)");
                return CHAT_REFUSAL;
            }
            // BE 이중 placeholder 가드 — GenAI가 빈칸을 뱉으면 안전 문구로 치환
            return sanitizePlaceholders(reply);
        } catch (Exception e) {
            log.error("[챗봇] GenAI 응답 실패: {}", e.getMessage());
            return "죄송합니다, 지금은 응답할 수 없습니다. 잠시 후 다시 시도해주세요.";
        }
    }

    record PriceResult(Map<String, Map<String, Object>> available, List<String> unavailable) {}

    /** 가격 조회 없이 언급된 DB 종목만 unavailable로 반환 — 상장 확인 컨텍스트 제공용 */
    private PriceResult buildListedTickersOnly(String message) {
        List<String> mentioned = tickerService.findMentionedTickers(message)
                .stream().map(TickerInfo::getTicker).toList();
        return new PriceResult(Map.of(), mentioned);
    }

    private PriceResult buildTickerPrices(String message) {
        List<TickerInfo> mentioned = tickerService.findMentionedTickers(message);
        if (mentioned.isEmpty()) return new PriceResult(Map.of(), List.of());

        Map<String, Map<String, Object>> prices = new HashMap<>();
        List<String> unavailable = new ArrayList<>();
        for (TickerInfo info : mentioned) {
            String ticker = info.getTicker();
            try {
                TechnicalsService.TechnicalsData td = technicalsService.getTechnicals(ticker);
                if (td != null && td.currentPrice() != null) {
                    Map<String, Object> detail = new HashMap<>();
                    detail.put("price", td.currentPrice());
                    if (td.openPrice() != null) detail.put("open", td.openPrice());
                    if (td.changePct1d() != null) detail.put("change_1d_pct", td.changePct1d());
                    if (td.changeOpenToClose() != null) detail.put("change_open_to_close_pct", td.changeOpenToClose());
                    prices.put(ticker, detail);
                } else {
                    unavailable.add(ticker);
                }
            } catch (Exception e) {
                log.debug("[챗봇] {} 가격 조회 실패: {}", ticker, e.getMessage());
                unavailable.add(ticker);
            }
        }
        return new PriceResult(prices, unavailable);
    }

    /** 메시지에 언급된 종목 중 상장폐지 예정이 있으면 안내 문구 반환, 없으면 null */
    private String buildDelistingNotice(String message) {
        return tickerService.findMentionedTickers(message).stream()
                .filter(TickerInfo::isDelistingPending)
                .map(info -> {
                    String name = (info.getKo() != null && !info.getKo().isBlank()) ? info.getKo() : info.getTicker();
                    return "⚠️ " + name + "(" + info.getTicker() + ")은 "
                            + info.getDelistingDate() + " 상장폐지 예정입니다.";
                })
                .reduce((a, b) -> a + "\n" + b)
                .orElse(null);
    }

    // ===================== 캐시 인사이트 라우터 (토큰 절감) =====================

    private static final List<String> INSIGHT_INTENT = List.of(
            "인사이트", "뉴스", "소식", "어때", "어떄", "전망", "동향", "현황", "분석", "오늘", "알려", "정보");

    private static boolean isInsightIntent(String msg) {
        return INSIGHT_INTENT.stream().anyMatch(msg::contains);
    }

    private static final List<String> WATCHLIST_INTENT = List.of(
            "관심종목", "관심 종목", "관심목록", "관심 목록", "내 종목",
            "내가 선택한", "내가 고른", "워치리스트", "watchlist");

    /**
     * "내 관심종목 뭐야" 류 질문에 워치리스트를 직접 응답 (LLM 토큰 0).
     * 특정 티커가 언급된 질문(예: "관심종목 AAPL 어때")은 그 종목 인사이트 의도이므로 제외하고,
     * 처리 불가하면 empty 반환 → 호출부에서 인사이트/LLM 폴백.
     */
    private Optional<String> tryWatchlistAnswer(String message, List<String> watchlist) {
        try {
            if (WATCHLIST_INTENT.stream().noneMatch(message::contains)) return Optional.empty();
            // 특정 티커가 언급된 질문은 그 종목에 대한 인사이트 의도 → 목록 응답에서 제외
            if (!tickerService.findMentionedTickers(message).isEmpty()) return Optional.empty();

            List<String> clean = watchlist == null ? List.of()
                    : watchlist.stream()
                        .map(t -> t.replace("\"", "").strip().toUpperCase())
                        .filter(s -> !s.isEmpty())
                        .distinct()
                        .toList();
            if (clean.isEmpty()) {
                return Optional.of("아직 관심 종목으로 등록한 티커가 없어요. "
                        + "뉴스 카드에서 오른쪽으로 스와이프하면 관심 종목에 추가할 수 있어요!");
            }
            return Optional.of("⭐ 현재 관심 종목 " + clean.size() + "개: " + String.join(", ", clean)
                    + "\n\n특정 종목이 궁금하면 \"" + clean.get(0) + " 어때?\"처럼 물어보세요.");
        } catch (Exception e) {
            log.warn("[챗봇] 워치리스트 응답 분기 실패 — 폴백: {}", e.getMessage());
            return Optional.empty();
        }
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
            // 비관심 종목 → LLM으로 위임 (시스템 프롬프트 규칙이 카드 안내로 처리)
            return Optional.empty();
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
                m.getTicker(), m.getArticleId(), m.getCreatedAt(), m.isRead());
    }
}
