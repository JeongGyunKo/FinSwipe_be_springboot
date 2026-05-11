package com.finswipe.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.finswipe.config.AppProperties;
import com.finswipe.domain.entity.NewsArticle;
import com.finswipe.domain.repository.NewsArticleRepository;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.data.domain.PageRequest;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientResponseException;

import java.net.URI;
import java.time.OffsetDateTime;
import java.util.*;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

@Service
@Slf4j
public class NewsCollectorService {

    // Python: COLLECTION_QUERIES
    private static final List<String> COLLECTION_QUERIES = List.of(
            "stock earnings",
            "stock market shares",
            "analyst rating stocks",
            "merger acquisition dividend",
            "Federal Reserve inflation rate",
            "semiconductor technology stocks",
            "energy oil bank stocks"
    );

    // Python: CRYPTO_TICKERS
    private static final Set<String> CRYPTO_TICKERS = Set.of(
            "BTC", "ETH", "BNB", "XRP", "ADA", "SOL", "DOGE", "DOT", "SHIB", "MATIC",
            "LTC", "TRX", "AVAX", "LINK", "UNI", "ATOM", "XLM", "ETC", "BCH", "ALGO",
            "VET", "ICP", "FIL", "THETA", "XMR", "EOS", "AAVE", "GRT", "MKR", "COMP",
            "SNX", "YFI", "SUSHI", "CRV", "BAT", "ZEC", "DASH", "NEO", "WAVES", "IOTA",
            "XTZ", "EGLD", "HBAR", "NEAR", "FTM", "ONE", "SAND", "MANA", "AXS", "ENJ",
            "CHZ", "FLOW", "GALA", "IMX", "APE", "LRC", "CRO", "KCS", "HT", "OKB",
            "USDT", "USDC", "BUSD", "DAI", "TUSD", "USDP", "FRAX", "LUSD", "USDD",
            "WBTC", "STETH", "RETH", "CBETH", "WETH",
            "SUI", "APT", "ARB", "OP", "BLUR", "PEPE", "FLOKI", "BONK", "WIF", "JUP"
    );

    private static final Pattern VALID_US_TICKER = Pattern.compile("^[A-Z]{1,5}$");
    private static final List<String> TRANSCRIPT_KEYWORDS = List.of("transcript", "conference call");

    private final RestClient finlightClient;
    private final NewsArticleRepository newsRepo;
    private final AnalyzerService analyzerService;
    private final NotificationService notificationService;
    private final ObjectMapper objectMapper;
    private final AppProperties props;

    private final AtomicBoolean analysisRunning = new AtomicBoolean(false);

    public NewsCollectorService(@Qualifier("finlightRestClient") RestClient finlightClient,
                                NewsArticleRepository newsRepo,
                                AnalyzerService analyzerService,
                                NotificationService notificationService,
                                ObjectMapper objectMapper,
                                AppProperties props) {
        this.finlightClient = finlightClient;
        this.newsRepo = newsRepo;
        this.analyzerService = analyzerService;
        this.notificationService = notificationService;
        this.objectMapper = objectMapper;
        this.props = props;
    }

    /** Python: collect_market_news() */
    public Map<String, Object> collectMarketNews() {
        log.info("뉴스 수집 시작...");
        List<NewsArticle> newArticles = fetchFromFinlight();

        if (newArticles.isEmpty()) {
            log.info("새 기사 없음 - 수집 종료");
            return Map.of("saved", 0, "skipped", 0, "analyzing", 0);
        }

        Map<String, Integer> result = saveArticles(newArticles);
        log.info("저장 완료 → {}개 저장, {}개 스킵", result.get("saved"), result.get("skipped"));

        if (result.get("saved") > 0) {
            Thread.ofVirtual().start(() -> {
                try {
                    analyzeAndUpdate(newArticles);
                } catch (Exception e) {
                    log.error("[백그라운드] 분석 파이프라인 예외: {}: {}", e.getClass().getSimpleName(), e.getMessage(), e);
                }
            });
            log.info("[백그라운드] GenAI 분석 예약 → {}개", result.get("saved"));
        }

        return Map.of("saved", result.get("saved"), "skipped", result.get("skipped"),
                "analyzing", result.get("saved"));
    }

    /** Python: fetch_news_from_finlight() */
    List<NewsArticle> fetchFromFinlight() {
        List<Map<String, Object>> allRaw = new ArrayList<>();

        for (String query : COLLECTION_QUERIES) {
            List<Map<String, Object>> articles = fetchSingleQuery(query);
            allRaw.addAll(articles);
            try { Thread.sleep(2000); } catch (InterruptedException e) { Thread.currentThread().interrupt(); break; }
        }

        // URL 중복 제거 + URL 정규화
        Map<String, Map<String, Object>> byUrl = new LinkedHashMap<>();
        for (var a : allRaw) {
            String link = (String) a.get("link");
            if (link != null) {
                String normalized = normalizeUrl(link);
                a.put("link", normalized);
                byUrl.putIfAbsent(normalized, a);
            }
        }
        log.info("[Finlight] 원본 {}개 → URL 중복제거 {}개", allRaw.size(), byUrl.size());

        // transcript 필터 + ticker 있는 기사만
        List<Map<String, Object>> withTickers = new ArrayList<>();
        int skippedTranscript = 0;
        for (var a : byUrl.values()) {
            String title = ((String) a.getOrDefault("title", "")).toLowerCase();
            if (TRANSCRIPT_KEYWORDS.stream().anyMatch(title::contains)) {
                skippedTranscript++;
                continue;
            }
            List<?> companies = (List<?>) a.getOrDefault("companies", List.of());
            if (!companies.isEmpty()) {
                withTickers.add(a);
            }
        }
        log.info("[Finlight] transcript 필터 제외: {}개", skippedTranscript);
        log.info("[Finlight] ticker 필터 통과: {}개 / {}개", withTickers.size(), byUrl.size());

        // DB 중복 제거
        List<String> links = withTickers.stream().map(a -> (String) a.get("link")).toList();
        Set<String> newLinks = filterNewLinks(links);
        List<Map<String, Object>> newArticles = withTickers.stream()
                .filter(a -> newLinks.contains((String) a.get("link")))
                .toList();
        log.info("[Finlight] 새 기사 {}개", newArticles.size());

        return newArticles.stream().map(this::toEntity).filter(Objects::nonNull).toList();
    }

    /** Python: _fetch_single_query() */
    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> fetchSingleQuery(String query) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("query", query);
        payload.put("language", "en");
        payload.put("pageSize", 100);
        payload.put("includeContent", true);
        payload.put("includeEntities", true);
        payload.put("excludeEmptyContent", true);
        payload.put("orderBy", "publishDate");
        payload.put("order", "DESC");

        for (int attempt = 0; attempt < 4; attempt++) {
            try {
                String raw = finlightClient.post()
                        .uri("/v2/articles")
                        .contentType(MediaType.APPLICATION_JSON)
                        .body(payload)
                        .retrieve()
                        .body(String.class);

                JsonNode root = objectMapper.readTree(raw);
                JsonNode articlesNode = root.path("articles");
                if (!articlesNode.isArray()) return List.of();

                List<Map<String, Object>> result = new ArrayList<>();
                articlesNode.forEach(node -> result.add(objectMapper.convertValue(node, Map.class)));

                if (!result.isEmpty()) {
                    Object pd = ((Map<?,?>) result.get(0)).get("publishDate");
                    String newest = pd != null ? pd.toString() : "";
                    log.info("[Finlight] '{}' → {}개 (최신: {})", query.length() > 40 ? query.substring(0, 40) : query,
                            result.size(), newest.length() >= 10 ? newest.substring(0, 10) : newest);
                } else {
                    log.info("[Finlight] '{}' → 0개", query);
                }
                return result;

            } catch (RestClientResponseException e) {
                if (e.getStatusCode().value() == 429) {
                    int wait = 15 * (attempt + 1);
                    log.warn("[Finlight] 429 → {}초 대기 후 재시도 ({}/4)", wait, attempt + 1);
                    try { Thread.sleep(wait * 1000L); } catch (InterruptedException ie) { Thread.currentThread().interrupt(); return List.of(); }
                    continue;
                }
                log.error("[Finlight] HTTP {}: {}", e.getStatusCode().value(), query);
                return List.of();
            } catch (Exception e) {
                log.error("[Finlight] {}: {}", e.getClass().getSimpleName(), query);
                return List.of();
            }
        }
        log.error("[Finlight] 4회 재시도 후 실패: {}", query);
        return List.of();
    }

    /** Python: _normalize_url() */
    private String normalizeUrl(String url) {
        try {
            URI uri = new URI(url);
            String path = uri.getPath();
            if (path != null) path = path.replaceAll("/$", "");
            return new URI(uri.getScheme(), uri.getAuthority(), path, null, null).toString();
        } catch (Exception e) {
            return url.replaceAll("/$", "");
        }
    }

    /** Python: _filter_new_links() */
    private Set<String> filterNewLinks(List<String> links) {
        if (links.isEmpty()) return Set.of();
        Set<String> existing = new HashSet<>();
        for (int i = 0; i < links.size(); i += 100) {
            List<String> chunk = links.subList(i, Math.min(i + 100, links.size()));
            try {
                existing.addAll(newsRepo.findExistingUrls(chunk));
            } catch (Exception e) {
                log.error("[Finlight] 기존 기사 조회 실패: {}", e.getMessage());
                return new HashSet<>(links);
            }
        }
        Set<String> result = new HashSet<>(links);
        result.removeAll(existing);
        return result;
    }

    /** Python: save_news_to_db() — Finlight 응답 raw map → NewsArticle 엔티티 변환 */
    @SuppressWarnings("unchecked")
    private NewsArticle toEntity(Map<String, Object> a) {
        String link = (String) a.get("link");
        String title = (String) a.get("title");
        if (link == null || title == null) return null;

        String content = ((String) a.getOrDefault("content", "")).strip();
        if (content.isEmpty()) return null;

        String summary = ((String) a.getOrDefault("summary", "")).strip();
        List<?> images = (List<?>) a.getOrDefault("images", List.of());
        List<?> categories = (List<?>) a.getOrDefault("categories", List.of());
        List<?> countries = (List<?>) a.getOrDefault("countries", List.of());
        List<?> companies = (List<?>) a.getOrDefault("companies", List.of());

        if (summary.isEmpty() && !content.isEmpty()) {
            summary = content.substring(0, Math.min(300, content.length())).strip();
        }

        List<String> tickers = filterTickers(companies.stream()
                .filter(c -> c instanceof Map)
                .map(c -> (String) ((Map<?, ?>) c).get("ticker"))
                .filter(Objects::nonNull)
                .toList());

        NewsArticle article = new NewsArticle();
        article.setHeadline(title);
        article.setSummary(summary.isEmpty() ? null : summary);
        article.setSourceUrl(link);
        article.setContent(content);
        article.setImageUrl(images.isEmpty() ? null : (String) images.get(0));
        article.setCategories(categories.stream().map(Object::toString).collect(Collectors.toList()));
        article.setCountries(countries.stream().map(Object::toString).collect(Collectors.toList()));
        article.setTickers(tickers);
        article.setPaywalled(false);

        String publishDate = (String) a.get("publishDate");
        if (publishDate != null) {
            try { article.setPublishedAt(OffsetDateTime.parse(publishDate)); } catch (Exception ignored) {}
        }
        return article;
    }

    /** Python: _filter_tickers() */
    List<String> filterTickers(List<String> tickers) {
        if (tickers == null) return List.of();
        return tickers.stream()
                .filter(t -> t != null && !t.isBlank())
                .map(String::toUpperCase)
                .filter(t -> VALID_US_TICKER.matcher(t).matches())
                .filter(t -> t.chars().allMatch(Character::isLetter))
                .filter(t -> !CRYPTO_TICKERS.contains(t))
                .distinct()
                .collect(Collectors.toList());
    }

    /** Python: save_news_to_db() */
    @Transactional
    Map<String, Integer> saveArticles(List<NewsArticle> articles) {
        if (articles.isEmpty()) return Map.of("saved", 0, "skipped", 0);
        try {
            // saveAll 반환값으로 ID를 원본 리스트에 반영 (이후 ID 기반 조회 가능)
            List<NewsArticle> saved = newsRepo.saveAll(articles);
            for (int i = 0; i < articles.size() && i < saved.size(); i++) {
                articles.get(i).setId(saved.get(i).getId());
            }
            return Map.of("saved", articles.size(), "skipped", 0);
        } catch (Exception e) {
            log.error("배치 저장 실패: {}", e.getMessage());
            return Map.of("saved", 0, "skipped", articles.size());
        }
    }

    /** Python: analyze_and_update() + _do_analyze_and_update()
     *  skipIfRunning=true: 재분석 스케줄러 (이미 실행 중이면 스킵)
     *  skipIfRunning=false: 신규 수집 기사 (항상 실행) */
    public void analyzeAndUpdate(List<NewsArticle> articles) {
        analyzeAndUpdate(articles, false);
    }

    public void analyzeAndUpdate(List<NewsArticle> articles, boolean skipIfRunning) {
        if (articles.isEmpty()) return;
        if (skipIfRunning) {
            if (!analysisRunning.compareAndSet(false, true)) {
                log.info("[백그라운드] 분석 진행 중 → 스킵 ({}개)", articles.size());
                return;
            }
        } else {
            analysisRunning.set(true);
        }
        try {
            doAnalyzeAndUpdate(articles);
        } finally {
            analysisRunning.set(false);
        }
    }

    private void doAnalyzeAndUpdate(List<NewsArticle> articles) {
        log.info("[백그라운드] GenAI 분석 시작 → {}개", articles.size());
        List<AnalyzerService.EnrichmentResult> results = analyzerService.analyzeBatch(articles);

        int updated = 0, failed = 0, skipped = 0;

        // URL 기반 매핑 — 인덱스 기반은 analyzeBatch 필터링 시 articles[i] ≠ results[i] 불일치 발생
        Map<String, AnalyzerService.EnrichmentResult> resultMap = results.stream()
                .filter(r -> r.getSourceUrl() != null)
                .collect(Collectors.toMap(
                        r -> r.getSourceUrl().replaceAll("/$", ""),
                        r -> r,
                        (a, b) -> a));

        for (NewsArticle original : articles) {
            String rawLink = original.getSourceUrl();
            if (rawLink == null) { skipped++; continue; }
            String link = rawLink.replaceAll("/$", "");

            AnalyzerService.EnrichmentResult result = resultMap.get(link);
            if (result == null) { skipped++; continue; }

            if (!result.isAvailable()) {
                if (result.isCleanFiltered()) {
                    try { newsRepo.markCleanFiltered(link); } catch (Exception e) {
                        log.error("[백그라운드] clean_filtered 표시 실패 ({}): {}", truncate(link), e.getMessage());
                    }
                }
                skipped++;
                continue;
            }

            try {
                Optional<NewsArticle> found = (original.getId() != null)
                        ? newsRepo.findById(original.getId())
                        : newsRepo.findBySourceUrl(link).or(() -> newsRepo.findBySourceUrl(link + "/"));

                if (found.isEmpty()) {
                    log.warn("[DB] 업데이트 0행 — 기사를 찾을 수 없음: {}", truncate(link));
                } else {
                    NewsArticle article = found.get();
                    article.setSentimentLabel(result.getSentimentLabel());
                    article.setSentimentScore(result.getSentimentScore());
                    article.setSummary3lines(result.getSummary3lines());
                    article.setXai(safeJson(result.getXai()));
                    article.setHeadlineKo(result.getHeadlineKo());
                    article.setSummary3linesKo(result.getSummary3linesKo());
                    article.setXaiKo(safeJson(result.getXaiKo()));
                    newsRepo.save(article);
                    log.info("[DB] 저장 완료: {}", truncate(link));
                }

                // 관심 종목 알림 발송
                List<String> tickers = original.getTickers();
                String headline = original.getHeadline();
                String fcmJson = resolveFcmJson();
                if (tickers != null && !tickers.isEmpty() && headline != null && fcmJson != null && !fcmJson.isBlank()) {
                    Thread.ofVirtual().start(() -> notificationService.notifyTickerArticle(headline, tickers, fcmJson));
                }
                updated++;
            } catch (Exception e) {
                failed++;
                log.error("[백그라운드] 업데이트 실패 ({}): {}", truncate(link), e.getMessage());
            }
        }
        log.info("[백그라운드] 완료 → 성공 {}개 / 실패 {}개 / 분석불가 {}개", updated, failed, skipped);
    }

    /** Python: reanalyze_unanalyzed() */
    public int reanalyzeUnanalyzed(int limit) {
        List<NewsArticle> unanalyzed = newsRepo.findUnanalyzed(PageRequest.of(0, limit));
        if (unanalyzed.isEmpty()) return 0;
        log.info("[재분석] 미분석 기사 {}개 발견 → 분석 시작", unanalyzed.size());
        analyzeAndUpdate(unanalyzed, true);
        return unanalyzed.size();
    }

    /** Python: cleanup_old_content() */
    @Transactional
    public void cleanupOldContent() {
        try {
            newsRepo.deleteArticlesWithoutContent();
            newsRepo.deleteArticlesWithoutTickers();
            log.info("[정리] content/tickers 없는 기사 삭제 완료");
        } catch (Exception e) {
            log.error("[정리] 삭제 실패: {}", e.getMessage());
        }
    }

    /**
     * FCM_SERVICE_ACCOUNT_JSON이 비어있으면 FCM_PROJECT_ID + FCM_CLIENT_EMAIL + FCM_PRIVATE_KEY로 JSON 조립.
     * 개행(\n)이 리터럴 문자열로 들어온 경우도 처리.
     */
    private String resolveFcmJson() {
        String json = props.getFcm().getServiceAccountJson();
        if (json != null && !json.isBlank()) return json;

        String projectId   = props.getFcm().getProjectId();
        String clientEmail = props.getFcm().getClientEmail();
        String privateKey  = props.getFcm().getPrivateKey();
        if (projectId.isBlank() || clientEmail.isBlank() || privateKey.isBlank()) return null;

        // 환경변수에서 \n이 리터럴로 들어오는 경우 실제 개행으로 변환
        privateKey = privateKey.replace("\\n", "\n");
        try {
            return objectMapper.writeValueAsString(java.util.Map.of(
                    "type", "service_account",
                    "project_id", projectId,
                    "client_email", clientEmail,
                    "private_key", privateKey,
                    "token_uri", "https://oauth2.googleapis.com/token"
            ));
        } catch (Exception e) {
            log.warn("[FCM] 서비스 계정 JSON 조립 실패: {}", e.getMessage());
            return null;
        }
    }

    /** xai/xai_ko 저장 전 JSON 유효성 검증 — 잘못된 JSON이면 null 반환 */
    private String safeJson(String json) {
        if (json == null) return null;
        try {
            objectMapper.readTree(json);
            return json;
        } catch (Exception e) {
            log.warn("[JSON] 유효하지 않은 JSON 무시: {}", json.length() > 50 ? json.substring(0, 50) : json);
            return null;
        }
    }

    private String truncate(String s) {
        return s != null && s.length() > 60 ? s.substring(0, 60) : s;
    }
}
