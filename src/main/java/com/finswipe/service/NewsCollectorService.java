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
import java.nio.charset.StandardCharsets;
import java.time.OffsetDateTime;
import java.util.*;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicInteger;
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

    private final AtomicBoolean reanalysisRunning = new AtomicBoolean(false);

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
        if (content.length() > 300) {
            String preview = content.substring(0, 300).stripTrailing();
            article.setContentPreview(preview.endsWith(".") ? preview : preview + "...");
        } else {
            article.setContentPreview(content);
        }
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
                // 5자리 워런트(W)·유닛(U)·라이츠(R)·임시(Z) 접미사 제외 — 보통주 아님
                .filter(t -> !(t.length() == 5 && "WURZ".indexOf(t.charAt(4)) >= 0))
                .distinct()
                .collect(Collectors.toList());
    }

    /** Python: save_news_to_db() — 기사 단위 저장으로 1개 실패가 전체 배치를 날리지 않도록 */
    Map<String, Integer> saveArticles(List<NewsArticle> articles) {
        if (articles.isEmpty()) return Map.of("saved", 0, "skipped", 0);
        int saved = 0, skipped = 0;
        for (NewsArticle article : articles) {
            try {
                NewsArticle persisted = newsRepo.save(article);
                article.setId(persisted.getId());
                saved++;
            } catch (Exception e) {
                log.warn("[DB] 기사 저장 실패 ({}): {}", truncate(article.getSourceUrl()), e.getMessage());
                skipped++;
            }
        }
        return Map.of("saved", saved, "skipped", skipped);
    }

    /** 신규 수집 기사 분석 — FCM 알림 발송 포함 */
    public void analyzeAndUpdate(List<NewsArticle> articles) {
        if (articles.isEmpty()) return;
        doAnalyzeAndUpdate(articles, true);
    }

    /** 재분석 전용 — FCM 알림 발송 안 함, 이미 실행 중이면 스킵 */
    public boolean analyzeAndUpdate(List<NewsArticle> articles, boolean skipIfRunning) {
        if (articles.isEmpty()) return true;
        if (!skipIfRunning) {
            doAnalyzeAndUpdate(articles, false);
            return true;
        }
        if (!reanalysisRunning.compareAndSet(false, true)) {
            log.info("[재분석] 이전 배치 실행 중 → 스킵 (대기 중 {}개)", articles.size());
            return false;
        }
        try {
            doAnalyzeAndUpdate(articles, false);
            return true;
        } finally {
            reanalysisRunning.set(false);
        }
    }

    private void doAnalyzeAndUpdate(List<NewsArticle> articles, boolean sendFcm) {
        log.info("[백그라운드] GenAI 분석 시작 → {}개 (분석 완료 즉시 저장)", articles.size());

        String fcmJson = resolveFcmJson();
        AtomicInteger updated = new AtomicInteger();
        AtomicInteger failed  = new AtomicInteger();
        AtomicInteger skipped = new AtomicInteger();
        AtomicInteger deleted = new AtomicInteger();

        // ID → DB 엔티티 사전 로딩 (N+1 방지)
        List<UUID> ids = articles.stream()
                .filter(a -> a.getId() != null).map(NewsArticle::getId).toList();
        Map<UUID, NewsArticle> dbArticles = ids.isEmpty() ? Map.of() :
                newsRepo.findAllById(ids).stream()
                        .collect(Collectors.toMap(NewsArticle::getId, a -> a));

        // 분석 완료 즉시 콜백으로 저장
        analyzerService.analyzeBatchStreaming(articles, (original, result) -> {
            String rawLink = original.getSourceUrl();
            if (rawLink == null) { skipped.incrementAndGet(); return; }
            String link = rawLink.replaceAll("/$", "");

            if (!result.isAvailable()) {
                if (result.isCleanFiltered()) {
                    try { newsRepo.markCleanFiltered(link); } catch (Exception e) {
                        log.error("[백그라운드] clean_filtered 표시 실패 ({}): {}", truncate(link), e.getMessage());
                    }
                }
                skipped.incrementAndGet();
                return;
            }

            // fatal_failure: GenAI 서버 내부 오류 (예: Pydantic 검증 실패) → 재시도해도 동일 결과, 영구 필터
            if ("fatal_failure".equals(result.getOutcome())) {
                log.info("[백그라운드] fatal_failure → _clean_filtered: {}", truncate(link));
                try { newsRepo.markCleanFiltered(link); } catch (Exception e) {
                    log.warn("[백그라운드] clean_filtered 마킹 실패 ({}): {}", truncate(link), e.getMessage());
                }
                deleted.incrementAndGet();
                return;
            }

            // xai_ko 없거나 영어 폴백인 경우
            boolean noValidXaiKo = result.getXaiKo() == null || !containsKorean(result.getXaiKo());
            if (noValidXaiKo) {
                if (isPressRelease(link)) {
                    try { newsRepo.markCleanFiltered(link); } catch (Exception e) {
                        log.warn("[백그라운드] clean_filtered 마킹 실패 ({}): {}", truncate(link), e.getMessage());
                    }
                    deleted.incrementAndGet();
                } else {
                    log.info("[백그라운드] xai 없음 (재시도 대기): {}", truncate(link));
                    skipped.incrementAndGet();
                }
                return;
            }

            try {
                // 한글 문자 포함 여부 검증 — Gemini 영어 폴백 방지
                String headlineKo = containsKorean(result.getHeadlineKo()) ? result.getHeadlineKo() : null;
                List<String> summaryKo = koreanLines(result.getSummary3linesKo());
                String xaiKo = containsKorean(result.getXaiKo()) ? safeJson(result.getXaiKo()) : null;

                NewsArticle article = (original.getId() != null) ? dbArticles.get(original.getId()) : null;
                if (article == null) {
                    article = newsRepo.findBySourceUrl(link)
                            .or(() -> newsRepo.findBySourceUrl(link + "/"))
                            .orElse(null);
                }
                if (article == null) {
                    log.warn("[DB] 업데이트 0행 — 기사를 찾을 수 없음: {}", truncate(link));
                } else {
                    article.setSentimentLabel(result.getSentimentLabel());
                    article.setSentimentScore(result.getSentimentScore());
                    article.setIsMixed("mixed".equals(result.getSentimentLabel()));
                    article.setSummary3lines(result.getSummary3lines());
                    article.setXai(safeJson(result.getXai()));
                    article.setHeadlineKo(headlineKo);
                    article.setSummary3linesKo(summaryKo);
                    article.setXaiKo(xaiKo);
                    newsRepo.save(article);
                    log.debug("[DB] 저장: {}", truncate(link));
                }
                // 3개 필드 모두 한국어로 있을 때만 알림
                if (sendFcm
                        && headlineKo != null
                        && summaryKo != null
                        && xaiKo != null) {
                    List<String> tickers = original.getTickers();
                    String headline = original.getHeadline();
                    if (tickers != null && !tickers.isEmpty() && headline != null
                            && fcmJson != null && !fcmJson.isBlank()) {
                        Thread.ofVirtual().start(() ->
                                notificationService.notifyTickerArticle(headline, tickers, fcmJson));
                    }
                }
                updated.incrementAndGet();
            } catch (Exception e) {
                // 다른 배치가 동시에 저장한 경우 → 이미 저장됨, 정상
                if (isStaleEntityException(e)) {
                    log.debug("[DB] 동시 저장 충돌 → 이미 저장됨: {}", truncate(link));
                    updated.incrementAndGet();
                } else {
                    failed.incrementAndGet();
                    log.error("[백그라운드] 업데이트 실패 ({}): {}", truncate(link), e.getMessage());
                }
            }
        });

        log.info("[백그라운드] 완료 → 성공 {}개 / 필터처리 {}개 / 실패 {}개 / 분석불가 {}개",
                updated.get(), deleted.get(), failed.get(), skipped.get());
    }

    /** Python: reanalyze_unanalyzed() */
    public int reanalyzeUnanalyzed(int limit) {
        List<NewsArticle> unanalyzed = newsRepo.findUnanalyzed(PageRequest.of(0, limit));
        if (unanalyzed.isEmpty()) return 0;
        log.info("[재분석] 미분석 기사 {}개 발견 → 분석 시작", unanalyzed.size());
        boolean ran = analyzeAndUpdate(unanalyzed, true);
        return ran ? unanalyzed.size() : 0;
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
        if (json != null && !json.isBlank()) {
            String trimmed = json.trim();
            if (!trimmed.startsWith("{")) {
                // Base64 인코딩된 경우 디코딩 (MIME → 표준 순서로 시도)
                for (Base64.Decoder decoder : List.of(
                        Base64.getMimeDecoder(), Base64.getDecoder(), Base64.getUrlDecoder())) {
                    try {
                        String decoded = new String(decoder.decode(trimmed), StandardCharsets.UTF_8).trim();
                        if (decoded.startsWith("{")) return decoded;
                    } catch (Exception ignored) {}
                }
                log.warn("[FCM] Base64 디코딩 실패 — 원본 값 그대로 사용");
            }
            return trimmed;
        }

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

    /** 한글 음절/자모 포함 여부 — Gemini 영어 폴백 감지용 */
    private boolean containsKorean(String text) {
        if (text == null || text.isBlank()) return false;
        return text.chars().anyMatch(c ->
                (c >= 0xAC00 && c <= 0xD7A3) ||  // 한글 음절
                (c >= 0x1100 && c <= 0x11FF) ||   // 한글 자모
                (c >= 0x3130 && c <= 0x318F));     // 한글 호환 자모
    }

    /** 리스트에서 한글 포함된 줄만 반환, 전부 영어면 null */
    private List<String> koreanLines(List<String> lines) {
        if (lines == null || lines.isEmpty()) return null;
        boolean hasKorean = lines.stream().anyMatch(this::containsKorean);
        return hasKorean ? lines : null;
    }

    private boolean isStaleEntityException(Exception e) {
        String msg = e.getMessage();
        if (msg != null && msg.contains("Row was already updated")) return true;
        Throwable cause = e.getCause();
        return cause != null && cause.getClass().getName().contains("StaleObject");
    }

    private boolean isPressRelease(String url) {
        if (url == null) return false;
        return url.contains("prnewswire.com") || url.contains("globenewswire.com")
                || url.contains("businesswire.com") || url.contains("accesswire.com");
    }

    private String truncate(String s) {
        return s != null && s.length() > 60 ? s.substring(0, 60) : s;
    }
}