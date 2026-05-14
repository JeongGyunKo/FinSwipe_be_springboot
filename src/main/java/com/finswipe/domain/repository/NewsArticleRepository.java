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

    // 최신 기사 페이징 — 한국어 완성 기사만 노출
    @Query(value = """
            SELECT * FROM news_articles
            WHERE headline_ko IS NOT NULL AND headline_ko ~ '[가-힣ㄱ-ㅎㅏ-ㅣ]'
              AND summary_3lines_ko IS NOT NULL AND summary_3lines_ko::text ~ '[가-힣ㄱ-ㅎㅏ-ㅣ]'
              AND xai_ko IS NOT NULL AND xai_ko::text ~ '[가-힣ㄱ-ㅎㅏ-ㅣ]'
            ORDER BY published_at DESC
            """,
            countQuery = """
            SELECT COUNT(*) FROM news_articles
            WHERE headline_ko IS NOT NULL AND headline_ko ~ '[가-힣ㄱ-ㅎㅏ-ㅣ]'
              AND summary_3lines_ko IS NOT NULL AND summary_3lines_ko::text ~ '[가-힣ㄱ-ㅎㅏ-ㅣ]'
              AND xai_ko IS NOT NULL AND xai_ko::text ~ '[가-힣ㄱ-ㅎㅏ-ㅣ]'
            """,
            nativeQuery = true)
    Page<NewsArticle> findByXaiKoIsNotNullOrderByPublishedAtDesc(Pageable pageable);

    // userId 기준 읽지 않은 기사 조회 — 사용자 관심 티커 + 한국어 완성 기사만
    @Query(value = """
            SELECT * FROM news_articles na
            WHERE na.headline_ko IS NOT NULL AND na.headline_ko ~ '[가-힣ㄱ-ㅎㅏ-ㅣ]'
              AND na.summary_3lines_ko IS NOT NULL AND na.summary_3lines_ko::text ~ '[가-힣ㄱ-ㅎㅏ-ㅣ]'
              AND na.xai_ko IS NOT NULL AND na.xai_ko::text ~ '[가-힣ㄱ-ㅎㅏ-ㅣ]'
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
            WHERE na.headline_ko IS NOT NULL AND na.headline_ko ~ '[가-힣ㄱ-ㅎㅏ-ㅣ]'
              AND na.summary_3lines_ko IS NOT NULL AND na.summary_3lines_ko::text ~ '[가-힣ㄱ-ㅎㅏ-ㅣ]'
              AND na.xai_ko IS NOT NULL AND na.xai_ko::text ~ '[가-힣ㄱ-ㅎㅏ-ㅣ]'
              AND na.tickers && (
                SELECT COALESCE(tickers, '{}') FROM user_profiles WHERE id = CAST(:userId AS uuid)
              )
              AND NOT EXISTS (
                SELECT 1 FROM user_read_articles
                WHERE user_id = CAST(:userId AS uuid) AND article_id = na.id
              )
            """,
            nativeQuery = true)
    Page<NewsArticle> findUnreadByUser(@Param("userId") String userId, Pageable pageable);

    // 특정 티커 기사 — 한국어 완성 기사만
    @Query(value = """
            SELECT id FROM news_articles
            WHERE tickers && CAST(:tickers AS text[])
              AND headline_ko IS NOT NULL AND headline_ko ~ '[가-힣ㄱ-ㅎㅏ-ㅣ]'
              AND summary_3lines_ko IS NOT NULL AND summary_3lines_ko::text ~ '[가-힣ㄱ-ㅎㅏ-ㅣ]'
              AND xai_ko IS NOT NULL AND xai_ko::text ~ '[가-힣ㄱ-ㅎㅏ-ㅣ]'
            ORDER BY published_at DESC LIMIT :limit OFFSET :offset
            """, nativeQuery = true)
    List<java.util.UUID> findIdsByTickersOverlap(@Param("tickers") String tickers,
                                                 @Param("limit") int limit,
                                                 @Param("offset") int offset);

    @Query(value = """
            SELECT COUNT(*) FROM news_articles
            WHERE tickers && CAST(:tickers AS text[])
              AND headline_ko IS NOT NULL AND headline_ko ~ '[가-힣ㄱ-ㅎㅏ-ㅣ]'
              AND summary_3lines_ko IS NOT NULL AND summary_3lines_ko::text ~ '[가-힣ㄱ-ㅎㅏ-ㅣ]'
              AND xai_ko IS NOT NULL AND xai_ko::text ~ '[가-힣ㄱ-ㅎㅏ-ㅣ]'
            """, nativeQuery = true)
    long countByTickersOverlap(@Param("tickers") String tickers);

    // ID 목록으로 순서 보장하며 엔티티 조회 (JPQL → StringListType 정상 동작)
    @Query("SELECT a FROM NewsArticle a WHERE a.id IN :ids ORDER BY a.publishedAt DESC")
    List<NewsArticle> findByIdIn(@Param("ids") List<java.util.UUID> ids);

    // 미분석 기사 조회 — 재분석 3회 미만만 대상 (3회 실패 시 영구 제외)
    @Query(value = """
            SELECT * FROM news_articles
            WHERE content IS NOT NULL
              AND (sentiment_label IS NULL OR sentiment_label != '_clean_filtered')
              AND retry_count < 3
              AND (
                sentiment_label IS NULL
                OR headline_ko IS NULL    OR headline_ko    !~ '[가-힣ㄱ-ㅎㅏ-ㅣ]'
                OR summary_3lines_ko IS NULL OR summary_3lines_ko::text !~ '[가-힣ㄱ-ㅎㅏ-ㅣ]'
                OR xai_ko IS NULL         OR xai_ko::text   !~ '[가-힣ㄱ-ㅎㅏ-ㅣ]'
              )
            ORDER BY published_at DESC
            LIMIT :limit
            """, nativeQuery = true)
    List<NewsArticle> findUnanalyzed(@Param("limit") int limit);

    // 재분석 실패 시 카운트 증가 — 3회 도달 시 자동으로 findUnanalyzed 대상에서 제외
    @Modifying
    @Transactional
    @Query(value = "UPDATE news_articles SET retry_count = retry_count + 1 WHERE source_url = :url AND retry_count < 3",
            nativeQuery = true)
    int incrementRetryCount(@Param("url") String url);

    // 최근 읽은 기사 조회 — 뒤로 보내기용 (읽은 순서 최신순)
    @Query(value = """
            SELECT na.* FROM news_articles na
            INNER JOIN user_read_articles ura ON ura.article_id = na.id
            WHERE ura.user_id = CAST(:userId AS uuid)
              AND na.headline_ko IS NOT NULL AND na.headline_ko ~ '[가-힣ㄱ-ㅎㅏ-ㅣ]'
              AND na.summary_3lines_ko IS NOT NULL AND na.summary_3lines_ko::text ~ '[가-힣ㄱ-ㅎㅏ-ㅣ]'
              AND na.xai_ko IS NOT NULL AND na.xai_ko::text ~ '[가-힣ㄱ-ㅎㅏ-ㅣ]'
              AND na.tickers && (
                SELECT COALESCE(tickers, '{}') FROM user_profiles WHERE id = CAST(:userId AS uuid)
              )
            ORDER BY ura.read_at DESC
            LIMIT :limit
            """, nativeQuery = true)
    List<NewsArticle> findRecentReadArticles(@Param("userId") String userId, @Param("limit") int limit);

    // 기존 URL 목록에서 이미 존재하는 URL 반환 (중복 제거용)
    @Query("SELECT a.sourceUrl FROM NewsArticle a WHERE a.sourceUrl IN :urls")
    List<String> findExistingUrls(@Param("urls") List<String> urls);

    // content NULL인 기사 삭제 (Python: cleanup_old_content)
    @Modifying
    @Transactional
    @Query(value = "DELETE FROM news_articles WHERE content IS NULL", nativeQuery = true)
    int deleteArticlesWithoutContent();

    // tickers 없는 기사 삭제 (Python: cleanup_old_content)
    @Modifying
    @Transactional
    @Query(value = "DELETE FROM news_articles WHERE tickers = '{}'", nativeQuery = true)
    int deleteArticlesWithoutTickers();

    // sentiment_label을 _clean_filtered로 업데이트 — 트랜잭션 없는 컨텍스트(가상 스레드)에서도 동작
    @Modifying
    @Transactional
    @Query(value = "UPDATE news_articles SET sentiment_label = '_clean_filtered' WHERE source_url = :url", nativeQuery = true)
    int markCleanFiltered(@Param("url") String url);
}
