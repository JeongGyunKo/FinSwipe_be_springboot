package com.finswipe.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.finswipe.config.AppProperties;
import com.finswipe.domain.entity.NewsArticle;
import com.finswipe.domain.repository.NewsArticleRepository;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestClient;

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

    // 전체 뉴스 스캔 — 최대 페이지 수 (15분 주기, 페이지당 100개)
    // 1콜 = 100기사, 최대 15페이지 × 96사이클 = 1,440콜/일, 20분 윈도우 적용 시 실측 ~350콜/일
    private static final int MAX_SCAN_PAGES = 15;

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
    // Finlight는 ISO MIC 코드를 사용 — 미국 거래소만 허용 (allowlist)
    // XNAS=NASDAQ, XNYS=NYSE, XASE=NYSE American, ARCX=NYSE Arca, BATS=CBOE BZX
    private static final Set<String> US_EXCHANGE_MICS = Set.of(
            "XNAS", "XNYS", "XASE", "ARCX", "BATS", "EDGX", "EDGA", "IEXG", "XOTC",
            // 단축명 fallback (혹시 Finlight가 섞어 쓸 경우)
            "NASDAQ", "NYSE", "AMEX", "ARCA", "OTC", "US");
    private static final List<String> TRANSCRIPT_KEYWORDS = List.of("transcript", "conference call");

    private final RestClient finlightClient;
    private final NewsArticleRepository newsRepo;
    private final AnalyzerService analyzerService;
    private final NotificationService notificationService;
    private final ChatService chatService;
    private final TechnicalsService technicalsService;
    private final TickerDiscoveryService tickerDiscoveryService;
    private final ObjectMapper objectMapper;
    private final AppProperties props;
    private final org.springframework.jdbc.core.JdbcTemplate jdbc;

    private final AtomicBoolean reanalysisRunning = new AtomicBoolean(false);
    private final AtomicBoolean freshAnalysisRunning = new AtomicBoolean(false);
    private final AtomicBoolean headlineTranslationRunning = new AtomicBoolean(false);

    public NewsCollectorService(@Qualifier("finlightRestClient") RestClient finlightClient,
                                NewsArticleRepository newsRepo,
                                AnalyzerService analyzerService,
                                NotificationService notificationService,
                                ChatService chatService,
                                TechnicalsService technicalsService,
                                TickerDiscoveryService tickerDiscoveryService,
                                ObjectMapper objectMapper,
                                AppProperties props,
                                org.springframework.jdbc.core.JdbcTemplate jdbc) {
        this.finlightClient = finlightClient;
        this.newsRepo = newsRepo;
        this.analyzerService = analyzerService;
        this.notificationService = notificationService;
        this.chatService = chatService;
        this.technicalsService = technicalsService;
        this.tickerDiscoveryService = tickerDiscoveryService;
        this.objectMapper = objectMapper;
        this.props = props;
        this.jdbc = jdbc;
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
                    // 사용자 관심 티커 기사만 분석 (비용 최적화)
                    List<NewsArticle> toAnalyze = filterByWatchedTickers(newArticles);
                    if (toAnalyze.isEmpty()) {
                        log.info("[백그라운드] 관심 티커 기사 없음 → 분석 스킵 (저장만 완료)");
                        return;
                    }
                    log.info("[백그라운드] 관심 티커 필터: {}개 → {}개", newArticles.size(), toAnalyze.size());
                    analyzeAndUpdate(toAnalyze);
                } catch (Exception e) {
                    log.error("[백그라운드] 분석 파이프라인 예외: {}: {}", e.getClass().getSimpleName(), e.getMessage(), e);
                }
            });
            log.info("[백그라운드] GenAI 분석 예약 → {}개 저장됨", result.get("saved"));
        }

        return Map.of("saved", result.get("saved"), "skipped", result.get("skipped"),
                "analyzing", result.get("saved"));
    }

    /** 전체 뉴스 스캔 — 필터 없이 가져와서 미국 티커로 자체 필터링 */
    List<NewsArticle> fetchFromFinlight() {
        Set<String> usTickers = loadUsTickers();
        List<Map<String, Object>> allRaw = new ArrayList<>();

        for (int page = 1; page <= MAX_SCAN_PAGES; page++) {
            List<Map<String, Object>> articles = fetchPage(page);
            if (articles.isEmpty()) break;

            // createdAt 기준 20분 이전이면 중단 (15분 주기 + 5분 안전 버퍼)
            Object lastDate = articles.get(articles.size() - 1).get("createdAt");
            if (lastDate == null) lastDate = articles.get(articles.size() - 1).get("publishDate");
            if (lastDate instanceof String dateStr) {
                java.time.Instant ingested = java.time.Instant.parse(dateStr);
                if (ingested.isBefore(java.time.Instant.now().minusSeconds(1200))) {
                    allRaw.addAll(articles);
                    log.info("[Finlight] 페이지 {} — 20분 이전 수집 기사 도달, 스캔 종료", page);
                    break;
                }
            }
            allRaw.addAll(articles);
            log.info("[Finlight] 페이지 {}/{} — {}개", page, MAX_SCAN_PAGES, articles.size());
            try { Thread.sleep(500); } catch (InterruptedException e) { Thread.currentThread().interrupt(); break; }
        }

        // 미국 티커만 남기고 기타 거래소 티커 제거
        for (Map<String, Object> article : allRaw) {
            filterToUsTickers(article, usTickers);
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

        // DB 중복 제거 (URL 기준)
        List<String> links = withTickers.stream().map(a -> (String) a.get("link")).toList();
        Set<String> newLinks = filterNewLinks(links);
        List<Map<String, Object>> newArticles = withTickers.stream()
                .filter(a -> newLinks.contains((String) a.get("link")))
                .toList();
        log.info("[Finlight] URL 중복 제거 후 {}개", newArticles.size());

        // 내용 유사도 중복 탐지 (다른 매체 동일 기사)
        List<Map<String, Object>> deduplicated = deduplicateSimilar(newArticles);
        int dupRemoved = newArticles.size() - deduplicated.size();
        if (dupRemoved > 0) log.info("[중복탐지] 유사 기사 {}개 제거됨", dupRemoved);

        // 신규 티커 감지 — companies 필드에서 ticker→corp 맵 수집 후 백그라운드 처리
        Map<String, String> tickerCorpMap = extractTickerCorpMap(deduplicated);
        if (!tickerCorpMap.isEmpty()) {
            Thread.ofVirtual().start(() -> tickerDiscoveryService.discoverNewTickers(tickerCorpMap));
        }

        return deduplicated.stream().map(this::toEntity).filter(Objects::nonNull).toList();
    }

    /** 미국 티커 목록 로드 (DB의 ticker_info 테이블 기준) */
    private Set<String> loadUsTickers() {
        try {
            List<String> list = jdbc.queryForList("SELECT ticker FROM ticker_info", String.class);
            return new java.util.HashSet<>(list);
        } catch (Exception e) {
            log.warn("[티커] ticker_info 로드 실패, VALID_US_TICKER 패턴으로 대체: {}", e.getMessage());
            return Set.of(); // 빈 셋 → 아래 filterToUsTickers에서 패턴 fallback
        }
    }

    /** 기사의 companies 리스트에서 미국 상장 티커만 남김 */
    @SuppressWarnings("unchecked")
    private void filterToUsTickers(Map<String, Object> article, Set<String> usTickers) {
        List<Map<String, Object>> companies = (List<Map<String, Object>>) article.getOrDefault("companies", List.of());
        if (companies.isEmpty()) return;
        List<Map<String, Object>> filtered = companies.stream()
                .filter(c -> {
                    String t = String.valueOf(c.getOrDefault("ticker", "")).toUpperCase();
                    // dot 포함 = 해외 거래소 접미사 (BA. = LSE:BA., BARC. = LSE:BARC. 등)
                    if (t.contains(".")) return false;
                    // exchange 필드가 있으면 비미국 거래소 제외
                    String exchange = String.valueOf(c.getOrDefault("exchange", "")).toUpperCase().strip();
                    if (!exchange.isBlank() && !US_EXCHANGE_MICS.contains(exchange)) {
                        log.info("[티커필터] 비미국 거래소 제외: {} ({})", t, exchange);
                        return false;
                    }
                    if (usTickers.isEmpty()) return VALID_US_TICKER.matcher(t).matches() && !CRYPTO_TICKERS.contains(t);
                    return usTickers.contains(t);
                })
                .toList();
        article.put("companies", filtered);
    }

    /** 기사 목록에서 ticker → corp(영문 회사명) 맵 추출 (신규 티커 감지용) */
    @SuppressWarnings("unchecked")
    private Map<String, String> extractTickerCorpMap(List<Map<String, Object>> articles) {
        Map<String, String> result = new LinkedHashMap<>();
        for (Map<String, Object> article : articles) {
            List<Map<String, Object>> companies =
                    (List<Map<String, Object>>) article.getOrDefault("companies", List.of());
            for (Map<String, Object> c : companies) {
                String ticker = String.valueOf(c.getOrDefault("ticker", "")).toUpperCase().strip();
                String name   = String.valueOf(c.getOrDefault("name", "")).strip();
                if (!ticker.isBlank() && !name.isBlank()) result.putIfAbsent(ticker, name);
            }
        }
        return result;
    }

    /** 필터 없이 Finlight 전체 뉴스 페이지 단위 조회 */
    @SuppressWarnings("unchecked")
    private List<Map<String, Object>> fetchPage(int page) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("query", "exchange:XNAS OR exchange:XNYS");
        payload.put("language", "en");
        payload.put("pageSize", 100);
        payload.put("page", page);
        payload.put("includeContent", true);
        payload.put("includeEntities", true);
        payload.put("excludeEmptyContent", true);
        payload.put("orderBy", "createdAt");
        payload.put("order", "DESC");

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
            return result;
        } catch (Exception e) {
            log.error("[Finlight] 페이지 {} 조회 실패: {}", page, e.getMessage());
            return List.of();
        }
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
    private NewsArticle toEntity(Map<String, Object> a) {
        String link = (String) a.get("link");
        String title = (String) a.get("title");
        if (link == null || title == null) return null;

        String content = ((String) a.getOrDefault("content", "")).strip();
        if (content.length() < 300) return null; // 3줄 요약 불가능한 너무 짧은 기사 제외

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

    /**
     * 중복 탐지: 같은 티커를 다루는 기사끼리만 비교.
     * 다른 종목 기사는 제목이 비슷해도 중복으로 처리하지 않음 (오탐 방지).
     * 같은 티커면 제목 75% + 본문 앞 300자 65% 유사도 동시 충족 시 중복 판단.
     */
    private List<Map<String, Object>> deduplicateSimilar(List<Map<String, Object>> articles) {
        // DB에서 최근 12시간 기사 제목 + 티커 조회
        List<String> recentTitles = new ArrayList<>();
        List<String> recentContents = new ArrayList<>();
        List<Set<String>> recentTickers = new ArrayList<>();
        try {
            List<Map<String, Object>> rows = jdbc.queryForList(
                    "SELECT headline, content_preview, tickers::text as tickers_text FROM news_articles WHERE created_at > NOW() - INTERVAL '12 hours'");
            rows.forEach(r -> {
                recentTitles.add(r.get("headline") != null ? r.get("headline").toString() : "");
                recentContents.add(r.get("content_preview") != null ? r.get("content_preview").toString() : "");
                recentTickers.add(parsePgArray(r.get("tickers_text")));
            });
        } catch (Exception e) {
            log.warn("[중복탐지] DB 조회 실패 → 배치 내 중복만 체크: {}", e.getMessage());
        }

        List<Map<String, Object>> result = new ArrayList<>();
        List<String> acceptedTitles = new ArrayList<>(recentTitles);
        List<String> acceptedContents = new ArrayList<>(recentContents);
        List<Set<String>> acceptedTickers = new ArrayList<>(recentTickers);

        for (Map<String, Object> article : articles) {
            String title = ((String) article.getOrDefault("title", "")).toLowerCase();
            String content = ((String) article.getOrDefault("content", ""));
            String contentSnippet = content.substring(0, Math.min(300, content.length())).toLowerCase();
            Set<String> tickers = extractTickers(article);

            boolean isDup = false;
            for (int i = 0; i < acceptedTitles.size(); i++) {
                // 티커가 둘 다 있고 겹치지 않으면 → 다른 종목 기사, 중복 아님
                Set<String> existingTickers = acceptedTickers.get(i);
                if (!tickers.isEmpty() && !existingTickers.isEmpty()) {
                    Set<String> intersection = new java.util.HashSet<>(tickers);
                    intersection.retainAll(existingTickers);
                    if (intersection.isEmpty()) continue;
                }

                double titleSim = jaccardSimilarity(tokenize(title), tokenize(acceptedTitles.get(i).toLowerCase()));
                if (titleSim >= 0.75) {
                    String existing = i < acceptedContents.size() ? acceptedContents.get(i) : "";
                    double contentSim = jaccardSimilarity(
                            tokenize(contentSnippet),
                            tokenize(existing.substring(0, Math.min(300, existing.length())).toLowerCase()));
                    if (contentSim >= 0.65) {
                        isDup = true;
                        break;
                    }
                }
            }

            if (!isDup) {
                result.add(article);
                acceptedTitles.add(title);
                acceptedContents.add(contentSnippet);
                acceptedTickers.add(tickers);
            }
        }
        return result;
    }

    private Set<String> extractTickers(Map<String, Object> article) {
        Set<String> result = new java.util.HashSet<>();
        Object companies = article.get("companies");
        if (companies instanceof List) {
            for (Object c : (List<?>) companies) {
                if (c instanceof Map) {
                    Object ticker = ((Map<?, ?>) c).get("ticker");
                    if (ticker != null && !ticker.toString().isBlank()) {
                        result.add(ticker.toString().toUpperCase());
                    }
                }
            }
        }
        return result;
    }

    private Set<String> parsePgArray(Object pgArray) {
        Set<String> result = new java.util.HashSet<>();
        if (pgArray == null) return result;
        String raw = pgArray.toString().replaceAll("[{}]", "").trim();
        if (raw.isBlank()) return result;
        for (String t : raw.split(",")) {
            if (!t.isBlank()) result.add(t.trim().toUpperCase());
        }
        return result;
    }

    private Set<String> tokenize(String text) {
        Set<String> words = new java.util.HashSet<>();
        for (String w : text.split("[\\W_]+")) {
            if (w.length() > 2) words.add(w); // 3자 이상 단어만
        }
        return words;
    }

    private double jaccardSimilarity(Set<String> a, Set<String> b) {
        if (a.isEmpty() && b.isEmpty()) return 1.0;
        if (a.isEmpty() || b.isEmpty()) return 0.0;
        Set<String> intersection = new java.util.HashSet<>(a);
        intersection.retainAll(b);
        Set<String> union = new java.util.HashSet<>(a);
        union.addAll(b);
        return (double) intersection.size() / union.size();
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
                article.setNoveltyScore(computeNoveltyScore(article));
                article.setPriceAtCollection(fetchPriceAtCollection(article));
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

    /** 수집 시점 대표 티커 주가 조회 — 장중이면 1분봉 현재가, 장외면 전일 종가. 실패 시 null. */
    private Double fetchPriceAtCollection(NewsArticle article) {
        List<String> tickers = article.getTickers();
        if (tickers == null || tickers.isEmpty()) return null;
        String ticker = tickers.get(0);
        try {
            TechnicalsService.TechnicalsData td = technicalsService.getTechnicals(ticker);
            return td != null ? td.currentPrice() : null;
        } catch (Exception e) {
            log.debug("[수집주가] {} 조회 실패: {}", ticker, e.getMessage());
            return null;
        }
    }

    /**
     * 최근 24시간 동일 티커 기사 헤드라인과 Jaccard 유사도를 비교해 참신도 계산.
     * 1.0 = 완전히 새로운 기사, 0.0 = 거의 동일한 기사 이미 존재
     */
    private double computeNoveltyScore(NewsArticle article) {
        try {
            if (article.getHeadline() == null || article.getHeadline().isBlank()) return 1.0;
            if (article.getTickers() == null || article.getTickers().isEmpty()) return 1.0;

            String tickersParam = "{" + String.join(",", article.getTickers()) + "}";
            List<String> recentHeadlines = jdbc.queryForList("""
                    SELECT headline FROM news_articles
                    WHERE tickers && CAST(? AS text[])
                      AND published_at >= NOW() - INTERVAL '24 hours'
                    LIMIT 50
                    """, String.class, tickersParam);

            if (recentHeadlines.isEmpty()) return 1.0;

            Set<String> tokens = tokenizeHeadline(article.getHeadline());
            double maxSimilarity = 0.0;
            for (String existing : recentHeadlines) {
                if (existing == null) continue;
                double sim = jaccardSimilarity(tokens, tokenizeHeadline(existing));
                if (sim > maxSimilarity) maxSimilarity = sim;
            }
            return Math.round((1.0 - maxSimilarity) * 100.0) / 100.0;
        } catch (Exception e) {
            log.debug("[novelty] 계산 실패, 기본값 1.0 사용: {}", e.getMessage());
            return 1.0;
        }
    }

    private Set<String> tokenizeHeadline(String headline) {
        Set<String> words = new java.util.HashSet<>();
        for (String w : headline.toLowerCase().split("[\\W_]+")) {
            if (w.length() > 2) words.add(w);
        }
        return words;
    }

    /** 신규 수집 기사 분석 — FCM 알림 발송 포함, 최우선 실행 */
    public void analyzeAndUpdate(List<NewsArticle> articles) {
        if (articles.isEmpty()) return;
        freshAnalysisRunning.set(true);
        try {
            doAnalyzeAndUpdate(articles, true);
        } finally {
            freshAnalysisRunning.set(false);
        }
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
                } else if (!sendFcm) {
                    // 재분석 모드에서 GenAI 타임아웃 → 재시도 카운트 증가
                    try { newsRepo.incrementRetryCount(link); } catch (Exception e) {
                        log.warn("[백그라운드] retry_count 증가 실패 ({}): {}", truncate(link), e.getMessage());
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

            // sentiment_reason 없는 경우
            if (result.getSentimentReason() == null) {
                if (isPressRelease(link)) {
                    try { newsRepo.markCleanFiltered(link); } catch (Exception e) {
                        log.warn("[백그라운드] clean_filtered 마킹 실패 ({}): {}", truncate(link), e.getMessage());
                    }
                    deleted.incrementAndGet();
                } else {
                    if (!sendFcm) {
                        try { newsRepo.incrementRetryCount(link); } catch (Exception e) {
                            log.warn("[백그라운드] retry_count 증가 실패 ({}): {}", truncate(link), e.getMessage());
                        }
                    }
                    log.info("[백그라운드] sentiment_reason 없음 (재시도 대기): {}", truncate(link));
                    skipped.incrementAndGet();
                }
                return;
            }

            try {
                // 한글 문자 포함 여부 검증 — Gemini 영어 폴백 방지
                String headlineKo = containsKorean(result.getHeadlineKo()) ? result.getHeadlineKo() : null;
                List<String> summaryKo = koreanLines(result.getSummary3linesKo());

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
                    article.setHeadlineKo(headlineKo);
                    article.setSummary3linesKo(summaryKo);
                    article.setSentimentReason(result.getSentimentReason());
                    if (result.getEventCategory() != null) {
                        article.setEventCategory(result.getEventCategory());
                    }
                    if (result.getSentimentDivergence() != null) {
                        article.setSentimentDivergence(result.getSentimentDivergence());
                    }
                    newsRepo.save(article);
                    log.debug("[DB] 저장: {}", truncate(link));
                }
                // 강한 감성(|score| >= 0.7) 기사만 알림 — 포트폴리오 알림 에이전트
                Double score = result.getSentimentScore();
                boolean isSignificant = score != null && Math.abs(score) >= 0.7;
                if (sendFcm
                        && isSignificant
                        && headlineKo != null
                        && summaryKo != null
                        && result.getSentimentReason() != null) {
                    List<String> tickers = original.getTickers();
                    String headline = headlineKo; // 한국어 헤드라인으로 알림
                    if (tickers != null && !tickers.isEmpty() && headline != null
                            && fcmJson != null && !fcmJson.isBlank()) {
                        Thread.ofVirtual().start(() ->
                                notificationService.notifyTickerArticle(headline, tickers, fcmJson));
                    }
                    if (tickers != null && !tickers.isEmpty()) {
                        final NewsArticle savedArticle = article;
                        final List<String> finalTickers = tickers;
                        Thread.ofVirtual().start(() ->
                                chatService.dispatchRecommendationAlerts(savedArticle, finalTickers));
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

    /** Python: reanalyze_unanalyzed() — 신규 기사 분석 중이면 스킵 */
    public int reanalyzeUnanalyzed(int limit) {
        if (freshAnalysisRunning.get()) {
            log.debug("[재분석] 신규 기사 분석 중 → 스킵");
            return 0;
        }
        List<NewsArticle> unanalyzed = newsRepo.findUnanalyzed(limit);
        if (unanalyzed.isEmpty()) return 0;
        log.info("[재분석] 미분석 기사 {}개 발견 (관심 티커 기준) → 분석 시작", unanalyzed.size());
        boolean ran = analyzeAndUpdate(unanalyzed, true);
        return ran ? unanalyzed.size() : 0;
    }

    /** 티커 필터 없이 전체 미분석 기사 재분석 — 인사이트 전체 재생성 등 배치용 */
    public int reanalyzeAll(int limit) {
        List<NewsArticle> unanalyzed = newsRepo.findUnanalyzedAll(limit);
        if (unanalyzed.isEmpty()) return 0;
        log.info("[전체 재분석] 미분석 기사 {}개 발견 → 분석 시작", unanalyzed.size());
        boolean ran = analyzeAndUpdate(unanalyzed, true);
        return ran ? unanalyzed.size() : 0;
    }

    /**
     * 사용자가 새 티커를 추가했을 때 최근 7일치 미분석 기사를 소급 분석.
     * UserProfileService 등에서 티커 업데이트 후 호출.
     *
     * @param newTickers 새로 추가된 티커 목록
     */
    public void triggerAnalysisForNewTickers(List<String> newTickers) {
        if (newTickers == null || newTickers.isEmpty()) return;

        // PostgreSQL text[] 리터럴 형식: {AAPL,NVDA}
        String tickersParam = "{" + String.join(",", newTickers) + "}";
        List<NewsArticle> articles = newsRepo.findUnanalyzedForTickers(tickersParam, 100);

        if (articles.isEmpty()) {
            log.info("[신규 티커] 미분석 기사 없음: {}", newTickers);
            return;
        }

        log.info("[신규 티커] 소급 분석 시작 → {}개 (티커: {})", articles.size(), newTickers);
        Thread.ofVirtual().start(() -> {
            try {
                doAnalyzeAndUpdate(articles, false);
            } catch (Exception e) {
                log.error("[신규 티커] 소급 분석 실패: {}", e.getMessage());
            }
        });
    }

    /**
     * 헤드라인 전용 번역 보정 — retry_count=3으로 막힌 관심 티커 기사 headline_ko를 경량 번역으로 채움.
     * 전체 enrichment 없이 headline만 번역하므로 빠르고 저렴함.
     */
    public int translateMissingHeadlines() {
        if (!headlineTranslationRunning.compareAndSet(false, true)) {
            return 0;
        }
        try {
            List<Map<String, Object>> rows = jdbc.queryForList("""
                    WITH watched AS (
                      SELECT array_agg(DISTINCT t) AS tickers
                      FROM user_profiles, unnest(tickers) AS t
                      WHERE tickers IS NOT NULL AND array_length(tickers, 1) > 0
                    )
                    SELECT na.id::text AS id, na.headline
                    FROM news_articles na
                    LEFT JOIN watched ON true
                    WHERE na.headline_ko IS NULL
                      AND na.content IS NOT NULL
                      AND (na.sentiment_label IS NULL OR na.sentiment_label != '_clean_filtered')
                      AND (watched.tickers IS NULL OR na.tickers && watched.tickers)
                    ORDER BY na.published_at DESC
                    LIMIT 20
                    """);
            if (rows.isEmpty()) return 0;

            List<Map<String, String>> items = rows.stream()
                    .filter(r -> r.get("id") != null && r.get("headline") != null)
                    .map(r -> Map.of("id", r.get("id").toString(), "headline", r.get("headline").toString()))
                    .toList();
            if (items.isEmpty()) return 0;

            Map<String, String> translations = analyzerService.translateHeadlinesBatch(items);
            if (translations.isEmpty()) return 0;

            int updated = 0;
            for (Map.Entry<String, String> entry : translations.entrySet()) {
                if (containsKorean(entry.getValue())) {
                    try {
                        int rows2 = jdbc.update(
                                "UPDATE news_articles SET headline_ko = ? WHERE id = CAST(? AS uuid) AND headline_ko IS NULL",
                                entry.getValue(), entry.getKey());
                        updated += rows2;
                    } catch (Exception e) {
                        log.warn("[헤드라인 번역] DB 업데이트 실패 ({}): {}", entry.getKey(), e.getMessage());
                    }
                }
            }
            if (updated > 0) {
                log.info("[헤드라인 번역] {}개 항목 처리 → {}개 headline_ko 저장", items.size(), updated);
            }
            return updated;
        } catch (Exception e) {
            log.error("[헤드라인 번역] 실패: {}", e.getMessage(), e);
            return 0;
        } finally {
            headlineTranslationRunning.set(false);
        }
    }

    /** Python: cleanup_old_content() */
    public void cleanupOldContent() {
        try {
            newsRepo.deleteArticlesWithoutContent();
        } catch (Exception e) {
            log.error("[정리] content 없는 기사 삭제 실패: {}", e.getMessage());
        }
        try {
            newsRepo.deleteArticlesWithoutTickers();
        } catch (Exception e) {
            log.error("[정리] tickers 없는 기사 삭제 실패: {}", e.getMessage());
        }
        log.info("[정리] content/tickers 없는 기사 삭제 완료");
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

    /**
     * 전체 사용자의 관심 티커를 조회한 뒤, 해당 티커를 포함하는 기사만 반환.
     * 관심 티커가 한 명도 없으면 원본 목록을 그대로 반환 (초기 상태 대비).
     */
    private List<NewsArticle> filterByWatchedTickers(List<NewsArticle> articles) {
        if (articles.isEmpty()) return articles;
        try {
            // 모든 사용자의 관심 티커를 flat하게 수집
            List<String> watchedTickers = jdbc.queryForList(
                    "SELECT DISTINCT t FROM user_profiles, unnest(tickers) AS t " +
                    "WHERE tickers IS NOT NULL AND array_length(tickers, 1) > 0",
                    String.class);

            if (watchedTickers.isEmpty()) {
                // 아직 티커를 선택한 사용자가 없으면 전체 분석 (초기 운영 시)
                return articles;
            }

            Set<String> watchedSet = new HashSet<>(watchedTickers);
            return articles.stream()
                    .filter(a -> a.getTickers() != null &&
                                 a.getTickers().stream().anyMatch(watchedSet::contains))
                    .toList();
        } catch (Exception e) {
            log.warn("[티커 필터] 관심 티커 조회 실패 → 전체 분석 ({})", e.getMessage());
            return articles; // 오류 시 안전하게 전체 처리
        }
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