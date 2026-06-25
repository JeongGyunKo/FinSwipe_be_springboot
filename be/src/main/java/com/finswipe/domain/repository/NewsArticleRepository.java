package com.finswipe.domain.repository;

import com.finswipe.domain.entity.NewsArticle;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

public interface NewsArticleRepository extends JpaRepository<NewsArticle, UUID> {

    Optional<NewsArticle> findBySourceUrl(String sourceUrl);

    // 최신 기사 페이징 — 시간순
    @Query(value = """
            SELECT * FROM news_articles
            WHERE headline_ko IS NOT NULL

              AND sentiment_reason IS NOT NULL
            ORDER BY published_at DESC
            """,
            countQuery = """
            SELECT COUNT(*) FROM news_articles
            WHERE headline_ko IS NOT NULL

              AND sentiment_reason IS NOT NULL
            """,
            nativeQuery = true)
    Page<NewsArticle> findByXaiKoIsNotNullOrderByPublishedAtDesc(Pageable pageable);

    // 오늘치 — ET 자정 이후 시간순
    @Query(value = """
            SELECT * FROM news_articles
            WHERE headline_ko IS NOT NULL

              AND sentiment_reason IS NOT NULL
              AND published_at >= :since
            ORDER BY published_at DESC
            """,
            countQuery = """
            SELECT COUNT(*) FROM news_articles
            WHERE headline_ko IS NOT NULL

              AND sentiment_reason IS NOT NULL
              AND published_at >= :since
            """,
            nativeQuery = true)
    Page<NewsArticle> findTodayOrderByPublishedAtDesc(@Param("since") java.time.OffsetDateTime since, Pageable pageable);

    // 오늘치 파워순
    @Query(value = """
            SELECT * FROM news_articles
            WHERE headline_ko IS NOT NULL

              AND sentiment_reason IS NOT NULL
              AND published_at >= :since
            ORDER BY ABS(sentiment_score) DESC NULLS LAST, published_at DESC
            """,
            countQuery = """
            SELECT COUNT(*) FROM news_articles
            WHERE headline_ko IS NOT NULL

              AND sentiment_reason IS NOT NULL
              AND published_at >= :since
            """,
            nativeQuery = true)
    Page<NewsArticle> findTodayOrderByPowerDesc(@Param("since") java.time.OffsetDateTime since, Pageable pageable);

    // 파워순 — 감성 강도(절대값) 높은 기사 우선
    @Query(value = """
            SELECT * FROM news_articles
            WHERE headline_ko IS NOT NULL

              AND sentiment_reason IS NOT NULL
            ORDER BY ABS(sentiment_score) DESC NULLS LAST, published_at DESC
            """,
            countQuery = """
            SELECT COUNT(*) FROM news_articles
            WHERE headline_ko IS NOT NULL

              AND sentiment_reason IS NOT NULL
            """,
            nativeQuery = true)
    Page<NewsArticle> findByXaiKoIsNotNullOrderByPowerDesc(Pageable pageable);

    // userId + 특정 티커 필터 읽지 않은 기사
    @Query(value = """
            SELECT * FROM news_articles na
            WHERE na.headline_ko IS NOT NULL

              AND na.sentiment_reason IS NOT NULL
              AND na.published_at >= :since
              AND :ticker = ANY(na.tickers)
              AND na.tickers && (
                SELECT COALESCE(tickers, '{}') FROM user_profiles WHERE id = CAST(:userId AS uuid)
              )
              AND NOT EXISTS (
                SELECT 1 FROM user_read_articles
                WHERE user_id = CAST(:userId AS uuid) AND article_id = na.id
              )
            ORDER BY na.published_at DESC
            """,
            countQuery = """
            SELECT COUNT(*) FROM news_articles na
            WHERE na.headline_ko IS NOT NULL

              AND na.sentiment_reason IS NOT NULL
              AND na.published_at >= :since
              AND :ticker = ANY(na.tickers)
              AND na.tickers && (
                SELECT COALESCE(tickers, '{}') FROM user_profiles WHERE id = CAST(:userId AS uuid)
              )
              AND NOT EXISTS (
                SELECT 1 FROM user_read_articles
                WHERE user_id = CAST(:userId AS uuid) AND article_id = na.id
              )
            """,
            nativeQuery = true)
    Page<NewsArticle> findUnreadByUserAndTicker(@Param("userId") String userId,
                                                @Param("since") java.time.OffsetDateTime since,
                                                @Param("ticker") String ticker,
                                                Pageable pageable);

    // userId 기준 읽지 않은 기사 — 티커별 균등 배분
    @Query(value = """
            WITH user_tickers AS (
              SELECT unnest(COALESCE(tickers, '{}')) AS ticker
              FROM user_profiles WHERE id = CAST(:userId AS uuid)
            ),
            ticker_count AS (
              SELECT COUNT(*) AS cnt FROM user_tickers
            ),
            ranked AS (
              SELECT na.*,
                ROW_NUMBER() OVER (
                  PARTITION BY (
                    SELECT t.ticker FROM user_tickers t WHERE t.ticker = ANY(na.tickers) LIMIT 1
                  )
                  ORDER BY na.published_at DESC
                ) AS rn,
                (SELECT cnt FROM ticker_count) AS total_tickers
              FROM news_articles na
              WHERE na.headline_ko IS NOT NULL
  
                AND na.sentiment_reason IS NOT NULL
                AND na.published_at >= :since
                AND na.tickers && (SELECT array_agg(ticker) FROM user_tickers)
                AND NOT EXISTS (
                  SELECT 1 FROM user_read_articles
                  WHERE user_id = CAST(:userId AS uuid) AND article_id = na.id
                )
            )
            SELECT *
            FROM ranked
            WHERE rn <= GREATEST(:perTicker, 10)
            ORDER BY published_at DESC
            """,
            countQuery = """
            SELECT COUNT(*) FROM news_articles na
            WHERE na.headline_ko IS NOT NULL

              AND na.sentiment_reason IS NOT NULL
              AND na.published_at >= :since
              AND na.tickers && (
                SELECT COALESCE(tickers, '{}') FROM user_profiles WHERE id = CAST(:userId AS uuid)
              )
              AND NOT EXISTS (
                SELECT 1 FROM user_read_articles
                WHERE user_id = CAST(:userId AS uuid) AND article_id = na.id
              )
            """,
            nativeQuery = true)
    Page<NewsArticle> findUnreadByUser(@Param("userId") String userId,
                                       @Param("since") java.time.OffsetDateTime since,
                                       @Param("perTicker") int perTicker,
                                       Pageable pageable);

    // 특정 티커 기사
    @Query(value = """
            SELECT id FROM news_articles
            WHERE tickers && CAST(:tickers AS text[])
              AND headline_ko IS NOT NULL AND headline_ko ~ '[가-힣ㄱ-ㅎㅏ-ㅣ]'

              AND sentiment_reason IS NOT NULL
            ORDER BY published_at DESC LIMIT :limit OFFSET :offset
            """, nativeQuery = true)
    List<java.util.UUID> findIdsByTickersOverlap(@Param("tickers") String tickers,
                                                 @Param("limit") int limit,
                                                 @Param("offset") int offset);

    @Query(value = """
            SELECT COUNT(*) FROM news_articles
            WHERE tickers && CAST(:tickers AS text[])
              AND headline_ko IS NOT NULL AND headline_ko ~ '[가-힣ㄱ-ㅎㅏ-ㅣ]'

              AND sentiment_reason IS NOT NULL
            """, nativeQuery = true)
    long countByTickersOverlap(@Param("tickers") String tickers);

    @Query("SELECT a FROM NewsArticle a WHERE a.id IN :ids ORDER BY a.publishedAt DESC")
    List<NewsArticle> findByIdIn(@Param("ids") List<java.util.UUID> ids);

    // 미분석 기사 — sentiment_reason 또는 summary_3lines_ko 없는 기사 대상
    @Query(value = """
            SELECT * FROM news_articles
            WHERE content IS NOT NULL
              AND (sentiment_label IS NULL OR sentiment_label != '_clean_filtered')
              AND retry_count < 3
              AND (
                sentiment_label IS NULL
                OR headline_ko IS NULL    OR headline_ko    !~ '[가-힣ㄱ-ㅎㅏ-ㅣ]'
                OR sentiment_reason IS NULL
                OR summary_3lines_ko IS NULL OR array_length(summary_3lines_ko, 1) = 0
              )
              AND (
                NOT EXISTS (
                  SELECT 1 FROM user_profiles
                  WHERE tickers IS NOT NULL AND array_length(tickers, 1) > 0
                )
                OR tickers && (
                  SELECT array_agg(DISTINCT t)
                  FROM user_profiles, unnest(tickers) AS t
                  WHERE tickers IS NOT NULL AND array_length(tickers, 1) > 0
                )
              )
            ORDER BY published_at DESC
            LIMIT :limit
            """, nativeQuery = true)
    List<NewsArticle> findUnanalyzed(@Param("limit") int limit);

    // 티커 필터 없이 전체 미분석 기사 (인사이트 전체 재생성 등 배치용)
    @Query(value = """
            SELECT * FROM news_articles
            WHERE content IS NOT NULL
              AND (sentiment_label IS NULL OR sentiment_label != '_clean_filtered')
              AND retry_count < 3
              AND (
                sentiment_label IS NULL
                OR headline_ko IS NULL    OR headline_ko    !~ '[가-힣ㄱ-ㅎㅏ-ㅣ]'

                OR sentiment_reason IS NULL
              )
            ORDER BY published_at DESC
            LIMIT :limit
            """, nativeQuery = true)
    List<NewsArticle> findUnanalyzedAll(@Param("limit") int limit);

    // 특정 티커 미분석 기사
    @Query(value = """
            SELECT * FROM news_articles
            WHERE content IS NOT NULL
              AND (sentiment_label IS NULL OR sentiment_label != '_clean_filtered')
              AND retry_count < 3
              AND (
                sentiment_label IS NULL
                OR headline_ko IS NULL    OR headline_ko    !~ '[가-힣ㄱ-ㅎㅏ-ㅣ]'

                OR sentiment_reason IS NULL
              )
              AND tickers && CAST(:tickers AS text[])
              AND published_at >= NOW() - INTERVAL '7 days'
            ORDER BY published_at DESC
            LIMIT :limit
            """, nativeQuery = true)
    List<NewsArticle> findUnanalyzedForTickers(@Param("tickers") String tickers,
                                               @Param("limit") int limit);

    @Modifying
    @Transactional
    @Query(value = "UPDATE news_articles SET retry_count = retry_count + 1 WHERE source_url = :url AND retry_count < 3",
            nativeQuery = true)
    int incrementRetryCount(@Param("url") String url);

    @Query(value = """
            SELECT na.* FROM news_articles na
            INNER JOIN user_read_articles ura ON ura.article_id = na.id
            WHERE ura.user_id = CAST(:userId AS uuid)
              AND na.headline_ko IS NOT NULL

              AND na.sentiment_reason IS NOT NULL
              AND na.published_at >= :since
              AND na.tickers && (
                SELECT COALESCE(tickers, '{}') FROM user_profiles WHERE id = CAST(:userId AS uuid)
              )
            ORDER BY ura.read_at DESC
            LIMIT :limit
            """, nativeQuery = true)
    List<NewsArticle> findRecentReadArticles(@Param("userId") String userId,
                                             @Param("since") java.time.OffsetDateTime since,
                                             @Param("limit") int limit);

    @Query("SELECT a.sourceUrl FROM NewsArticle a WHERE a.sourceUrl IN :urls")
    List<String> findExistingUrls(@Param("urls") List<String> urls);

    @Modifying
    @Transactional
    @Query(value = "DELETE FROM news_articles WHERE content IS NULL", nativeQuery = true)
    int deleteArticlesWithoutContent();

    @Modifying
    @Transactional
    @Query(value = "DELETE FROM news_articles WHERE tickers = '{}'", nativeQuery = true)
    int deleteArticlesWithoutTickers();

    @Modifying
    @Transactional
    @Query(value = "UPDATE news_articles SET sentiment_label = '_clean_filtered' WHERE source_url = :url", nativeQuery = true)
    int markCleanFiltered(@Param("url") String url);
}
