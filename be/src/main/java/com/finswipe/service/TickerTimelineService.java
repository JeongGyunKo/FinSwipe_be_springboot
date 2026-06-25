package com.finswipe.service;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.time.DayOfWeek;
import java.time.Duration;
import java.time.Instant;
import java.time.LocalDate;
import java.time.LocalTime;
import java.time.ZoneId;
import java.time.ZonedDateTime;
import java.time.temporal.TemporalAdjusters;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.UnaryOperator;

/**
 * 종목 멀티데이 이벤트 타임라인.
 * 기사 발행 시각을 미국 거래 세션(16:00 ET 마감) 단위로 버킷팅해 최근 N개 세션을 반환한다.
 * 어드민 프리뷰(/admin/ticker-timeline)와 사용자 앱(/analysis/ticker-timeline) 양쪽에서 사용.
 */
@Service
public class TickerTimelineService {

    private final JdbcTemplate jdbc;

    public TickerTimelineService(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    /**
     * @param rawTicker      종목 심볼
     * @param sessionsWanted 반환할 최근 세션 수(1~10)
     * @return { ticker, sessions:[{ date, label, count, sentiment, avgScore, articles:[{headlineKo,sentimentLabel,sentimentScore}] }] }
     * @throws IllegalArgumentException ticker 형식 오류
     */
    public Map<String, Object> getTimeline(String rawTicker, int sessionsWanted) {
        String sym = rawTicker == null ? "" : rawTicker.replace("\"", "").strip().toUpperCase();
        if (!sym.matches("[A-Z][A-Z.\\-]{0,11}")) {
            throw new IllegalArgumentException("유효하지 않은 ticker");
        }
        int want = Math.min(Math.max(sessionsWanted, 1), 10);
        // 세션 want개를 채우려면 주말·휴장 고려해 넉넉히 조회
        Instant since = Instant.now().minus(Duration.ofDays(want * 3L + 7L));

        List<Map<String, Object>> rows = jdbc.query(
                """
                SELECT headline_ko, sentiment_label, sentiment_score, published_at
                FROM news_articles
                WHERE ? = ANY(tickers)
                  AND headline_ko IS NOT NULL AND headline_ko ~ '[가-힣ㄱ-ㅎㅏ-ㅣ]'
                  AND sentiment_reason IS NOT NULL
                  AND published_at >= ?
                ORDER BY published_at DESC
                """,
                (rs, i) -> {
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("headlineKo", rs.getString("headline_ko"));
                    m.put("sentimentLabel", rs.getString("sentiment_label"));
                    Object sc = rs.getObject("sentiment_score");
                    m.put("sentimentScore", sc == null ? null : ((Number) sc).doubleValue());
                    java.sql.Timestamp ts = rs.getTimestamp("published_at");
                    m.put("_instant", ts == null ? null : ts.toInstant());
                    return m;
                },
                sym, java.sql.Timestamp.from(since));

        TreeMap<LocalDate, List<Map<String, Object>>> bySession = new TreeMap<>();
        for (Map<String, Object> r : rows) {
            Instant inst = (Instant) r.get("_instant");
            if (inst == null) continue;
            bySession.computeIfAbsent(tradingSession(inst), k -> new ArrayList<>()).add(r);
        }

        List<LocalDate> dates = new ArrayList<>(bySession.keySet());
        if (dates.size() > want) dates = dates.subList(dates.size() - want, dates.size());

        List<Map<String, Object>> out = new ArrayList<>();
        for (LocalDate date : dates) {
            List<Map<String, Object>> arts = bySession.get(date);
            arts.sort((a, b) -> Double.compare(absScore(b), absScore(a)));
            double sum = 0;
            int n = 0;
            for (Map<String, Object> a : arts) {
                Object s = a.get("sentimentScore");
                if (s != null) { sum += ((Number) s).doubleValue(); n++; }
            }
            double avg = n > 0 ? sum / n : 0;
            String sentiment = avg > 0.15 ? "positive" : avg < -0.15 ? "negative" : "neutral";

            List<Map<String, Object>> top = new ArrayList<>();
            for (Map<String, Object> a : arts.subList(0, Math.min(2, arts.size()))) {
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("headlineKo", a.get("headlineKo"));
                m.put("sentimentLabel", a.get("sentimentLabel"));
                m.put("sentimentScore", a.get("sentimentScore"));
                top.add(m);
            }
            Map<String, Object> sess = new LinkedHashMap<>();
            sess.put("date", date.toString());                            // 미국 거래일 ISO
            sess.put("label", date.getMonthValue() + "/" + date.getDayOfMonth());
            sess.put("count", arts.size());
            sess.put("sentiment", sentiment);
            sess.put("avgScore", Math.round(avg * 100) / 100.0);
            sess.put("articles", top);
            out.add(sess);
        }

        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("ticker", sym);
        resp.put("sessions", out);
        return resp;
    }

    private static double absScore(Map<String, Object> a) {
        Object s = a.get("sentimentScore");
        return s == null ? 0 : Math.abs(((Number) s).doubleValue());
    }

    // ── 미국 거래 세션(16:00 ET 마감) 계산 ──────────────────────────────
    private static final ZoneId MARKET_ZONE = ZoneId.of("America/New_York");
    private static final LocalTime MARKET_CLOSE = LocalTime.of(16, 0);
    private static final Map<Integer, Set<LocalDate>> HOLIDAY_CACHE = new ConcurrentHashMap<>();
    // 예고 없는 임시 휴장(대통령 국장일, 9/11·허리케인 등 비정기) — 발표되면 여기에만 추가.
    private static final Set<LocalDate> AD_HOC_CLOSURES = Set.of(
            LocalDate.of(2025, 1, 9));   // 카터 전 대통령 국장

    /** 기사 발행 시각이 속하는 미국 거래 세션(마감일). 16:00 ET 이전이면 그 날, 이후면 다음 거래일. */
    private static LocalDate tradingSession(Instant t) {
        ZonedDateTime et = t.atZone(MARKET_ZONE);
        LocalDate d = et.toLocalDate();
        if (et.toLocalTime().isAfter(MARKET_CLOSE)) d = d.plusDays(1);
        while (marketClosed(d)) d = d.plusDays(1);
        return d;
    }

    /** 토·일·정기휴장·임시휴장 여부. 연도 무관 자동 계산. */
    private static boolean marketClosed(LocalDate d) {
        DayOfWeek w = d.getDayOfWeek();
        if (w == DayOfWeek.SATURDAY || w == DayOfWeek.SUNDAY) return true;
        if (AD_HOC_CLOSURES.contains(d)) return true;
        return HOLIDAY_CACHE.computeIfAbsent(d.getYear(), TickerTimelineService::usMarketHolidays).contains(d);
    }

    /** 해당 연도 미국 증시 정기 휴장일 10종 계산(고정일·N번째 요일·Good Friday). */
    private static Set<LocalDate> usMarketHolidays(int year) {
        Set<LocalDate> h = new HashSet<>();
        UnaryOperator<LocalDate> obs = d -> switch (d.getDayOfWeek()) {
            case SATURDAY -> d.minusDays(1);   // 토 → 전날 금
            case SUNDAY -> d.plusDays(1);      // 일 → 다음 월
            default -> d;
        };
        h.add(obs.apply(LocalDate.of(year, 1, 1)));      // 신정
        if (year >= 2022) h.add(obs.apply(LocalDate.of(year, 6, 19)));  // 준틴스(2022~)
        h.add(obs.apply(LocalDate.of(year, 7, 4)));      // 독립기념일
        h.add(obs.apply(LocalDate.of(year, 12, 25)));    // 크리스마스
        var mon3 = TemporalAdjusters.dayOfWeekInMonth(3, DayOfWeek.MONDAY);
        h.add(LocalDate.of(year, 1, 1).with(mon3));      // MLK(1월 3째 월)
        h.add(LocalDate.of(year, 2, 1).with(mon3));      // 워싱턴 탄생일(2월 3째 월)
        h.add(LocalDate.of(year, 5, 1).with(TemporalAdjusters.lastInMonth(DayOfWeek.MONDAY)));             // 메모리얼(5월 마지막 월)
        h.add(LocalDate.of(year, 9, 1).with(TemporalAdjusters.dayOfWeekInMonth(1, DayOfWeek.MONDAY)));     // 노동절(9월 1째 월)
        h.add(LocalDate.of(year, 11, 1).with(TemporalAdjusters.dayOfWeekInMonth(4, DayOfWeek.THURSDAY)));  // 추수감사절(11월 4째 목)
        h.add(easterSunday(year).minusDays(2));          // Good Friday
        return h;
    }

    /** 그레고리력 부활절(Meeus/Jones/Butcher 알고리즘). */
    private static LocalDate easterSunday(int year) {
        int a = year % 19, b = year / 100, c = year % 100;
        int dd = b / 4, e = b % 4, f = (b + 8) / 25, g = (b - f + 1) / 3;
        int hh = (19 * a + b - dd - g + 15) % 30;
        int i = c / 4, k = c % 4;
        int l = (32 + 2 * e + 2 * i - hh - k) % 7;
        int m = (a + 11 * hh + 22 * l) / 451;
        int month = (hh + l - 7 * m + 114) / 31;
        int day = ((hh + l - 7 * m + 114) % 31) + 1;
        return LocalDate.of(year, month, day);
    }
}
