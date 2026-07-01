package com.finswipe.service;

import com.finswipe.domain.entity.NewsArticle;
import com.finswipe.domain.repository.NewsArticleRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

/**
 * 카드 피드 개인화 재정렬(에이전트형 큐레이션의 "행동(Act)" 단계).
 *
 * 후보 = 오늘 파워 상위 pool개(읽음/싫어요 제외) → 유저 행동 선호(종목 친밀도)로 재정렬 →
 * 상위(개인화) + 탐색 쿼터(순수 파워)로 size개 구성. 신호가 없으면 순수 파워순으로 폴백(콜드스타트).
 *
 * 선호도는 별도 집계 테이블 없이 매 요청 시 신호 테이블에서 즉석 계산(compute-on-read) —
 * 항상 최신 신호를 반영하는 학습 루프. 규모가 커지면 materialized affinity로 최적화 가능.
 */
@Service
@RequiredArgsConstructor
@Slf4j
public class FeedRankingService {

    private final NewsArticleRepository newsRepo;
    private final JdbcTemplate jdbc;

    private static final int POOL_CAP = 120;   // 후보 풀 크기(오늘 파워 상위)
    private static final int EXPLORE = 6;       // size 중 탐색(순수 파워) 슬롯 — 필터버블 방지
    private static final double W_AFF = 0.15;   // 종목 친밀도 가중치
    private static final double AFF_CLAMP = 6.0;

    /** 종목 친밀도 집계 — 좋아요(+3)/싫어요(-4)/읽음(+0.5)/체류(+최대2), 21일 반감 시간감쇠, 최근 90일. */
    private static final String AFFINITY_SQL = """
            SELECT ticker, SUM(w) AS score FROM (
              SELECT unnest(na.tickers) AS ticker,
                     3.0  * exp(-EXTRACT(EPOCH FROM (now() - ula.liked_at))    / (86400.0*21)) AS w
              FROM user_liked_articles ula JOIN news_articles na ON na.id = ula.article_id
              WHERE ula.user_id = CAST(? AS UUID) AND ula.liked_at > now() - interval '90 days'
              UNION ALL
              SELECT unnest(na.tickers),
                     -4.0 * exp(-EXTRACT(EPOCH FROM (now() - uda.disliked_at)) / (86400.0*21))
              FROM user_disliked_articles uda JOIN news_articles na ON na.id = uda.article_id
              WHERE uda.user_id = CAST(? AS UUID) AND uda.disliked_at > now() - interval '90 days'
              UNION ALL
              SELECT unnest(na.tickers),
                     0.5  * exp(-EXTRACT(EPOCH FROM (now() - ura.read_at))     / (86400.0*21))
              FROM user_read_articles ura JOIN news_articles na ON na.id = ura.article_id
              WHERE ura.user_id = CAST(? AS UUID) AND ura.read_at > now() - interval '90 days'
              UNION ALL
              SELECT unnest(na.tickers),
                     LEAST(2.0, uce.dwell_ms / 8000.0)
                       * exp(-EXTRACT(EPOCH FROM (now() - uce.created_at))      / (86400.0*21))
              FROM user_card_events uce JOIN news_articles na ON na.id = uce.article_id
              WHERE uce.user_id = CAST(? AS UUID) AND uce.event_type = 'dwell'
                AND uce.dwell_ms IS NOT NULL AND uce.created_at > now() - interval '90 days'
            ) s
            GROUP BY ticker
            """;

    /** 개인화 재정렬된 피드 size개 반환. */
    public List<NewsArticle> rankFeed(String userId, OffsetDateTime since, int size) {
        List<NewsArticle> pool = newsRepo.findTopPowerUnreadForUser(userId, since, POOL_CAP);
        if (pool.size() <= size) return pool;   // 후보가 적으면 있는 대로

        Map<String, Double> affinity = tickerAffinity(userId);
        if (affinity.isEmpty()) return new ArrayList<>(pool.subList(0, size));  // 콜드스타트 = 순수 파워

        // 점수 = 파워(0~1) + W_AFF × 종목친밀도(clamp). pool은 이미 파워순.
        Map<UUID, Double> score = new HashMap<>();
        for (NewsArticle a : pool) score.put(a.getId(), scoreOf(a, affinity));

        List<NewsArticle> byScore = new ArrayList<>(pool);
        byScore.sort((x, y) -> Double.compare(score.get(y.getId()), score.get(x.getId())));

        int personalN = Math.max(0, size - EXPLORE);
        List<NewsArticle> result = new ArrayList<>(byScore.subList(0, Math.min(personalN, byScore.size())));
        Set<UUID> chosen = new HashSet<>();
        for (NewsArticle a : result) chosen.add(a.getId());

        // 탐색 쿼터: pool(순수 파워순)에서 아직 안 뽑힌 최고 파워 기사로 나머지 채움
        for (NewsArticle a : pool) {
            if (result.size() >= size) break;
            if (chosen.add(a.getId())) result.add(a);
        }
        return result;
    }

    private double scoreOf(NewsArticle a, Map<String, Double> affinity) {
        double power = a.getSentimentScore() != null ? Math.abs(a.getSentimentScore()) / 100.0 : 0.0;
        double tickerAff = 0.0;   // 기사 종목 중 |친밀도|가 가장 큰 값(호재 강화·기피 종목 감점 모두 반영)
        if (a.getTickers() != null) {
            for (String t : a.getTickers()) {
                double v = affinity.getOrDefault(t, 0.0);
                if (Math.abs(v) > Math.abs(tickerAff)) tickerAff = v;
            }
        }
        tickerAff = Math.max(-AFF_CLAMP, Math.min(AFF_CLAMP, tickerAff));
        return power + W_AFF * tickerAff;
    }

    private Map<String, Double> tickerAffinity(String userId) {
        try {
            List<Map<String, Object>> rows = jdbc.queryForList(AFFINITY_SQL, userId, userId, userId, userId);
            Map<String, Double> m = new HashMap<>();
            for (Map<String, Object> r : rows) {
                String t = (String) r.get("ticker");
                Object s = r.get("score");
                if (t != null && s instanceof Number n) m.put(t, n.doubleValue());
            }
            return m;
        } catch (Exception e) {
            log.warn("[랭킹] 종목 친밀도 집계 실패, 순수 파워로 폴백: {}", e.getMessage());
            return Map.of();
        }
    }
}
