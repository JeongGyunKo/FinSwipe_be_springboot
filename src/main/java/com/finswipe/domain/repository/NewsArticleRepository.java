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

    // 한국어 완성 기사 공통 조건 (NULL 체크 + 한글 포함 여부)
    // headline_ko, summary_3lines_ko, xai_ko 셋 모두 한글 포함 필수
    String KOREAN_COMPLETE =
            "headline_ko IS NOT NULL AND headline_ko ~ '[가-힣ㄱ-ㅎㅏ-ㅣ]' " +
            "AND summary_3lines_ko IS NOT NULL AND summary_3lines_ko::text ~ '[가-힣ㄱ-ㅎㅏ-ㅣ]' " +
            "AND xai_ko IS NOT NULL AND xai_ko::text ~ '[가-힣ㄱ-ㅎㅏ-ㅣ]'";

    // 최신 기사 페이징 — 한국어 완성 기사만 노출
    @Query(value = """
            SELECT * FROM news_articles
            WHERE headline_ko IS NOT NULL AND headline_ko ~ '[가-힣ㄱ-ㅎㅏ-ㅣ]'
              AND summary_3lines_ko IS NOT NULL AND summary_3lines_ko::text ~ '[가-힣ㄱ-ㅎㅏ-ㅣ]'
              AND xai_ko IS NOT NULL AND xai_ko::text ~ '[가-힣ㄱ-ㅎㅏ-ㅣ]'
            ORDER BY published_at DESC
            """, nativeQuery = true)
    Page<NewsArticle> findByXaiKoIsNotNullOrderByPublishedAtDesc(Pageable pageable);

    // userId 기준 읽지 않은 기사 조회 — 한국어 완성 기사만
    @Query(value = """
            SELECT * FROM news_articles
            WHERE headline_ko IS NOT NULL AND headline_ko ~ '[가-힣ㄱ-ㅎㅏ-ㅣ]'
              AND summary_3lines_ko IS NOT NULL AND summary_3lines_ko::text ~ '[가-힣ㄱ-ㅎㅏ-ㅣ]'
              AND xai_ko IS NOT NULL AND xai_ko::text ~ '[가-힣ㄱ-ㅎㅏ-ㅣ]'
              AND id NOT IN (
                SELECT article_id FROM user_read_articles WHERE user_id = :userId::uuid
              )
            ORDER BY published_at DESC
            LIMIT :limit OFFSET :offset
            """, nativeQuery = true)
    List<NewsArticle> findUnreadByUser(@Param("userId") String userId,
                                       @Param("limit") int limit,
                                       @Param("offset") int offset);

    @Query(value = """
            SELECT COUNT(*) FROM news_articles
            WHERE headline_ko IS NOT NULL AND headline_ko ~ '[가-힣ㄱ-ㅎㅏ-ㅣ]'
              AND summary_3lines_ko IS NOT NULL AND summary_3lines_ko::text ~ '[가-힣ㄱ-ㅎㅏ-ㅣ]'
              AND xai_ko IS NOT NULL AND xai_ko::text ~ '[가-힣ㄱ-ㅎㅏ-ㅣ]'
              AND id NOT IN (
                SELECT article_id FROM user_read_articles WHERE user_id = :userId::uuid
              )
            """, nativeQuery = true)
    long countUnreadByUser(@Param("userId") String userId);

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

    // 미분석 기사 조회 — 생성 후 3시간 이내만 재시도 (번역 실패 무한 루프 방지)
    @Query(value = """
            SELECT * FROM news_articles
            WHERE content IS NOT NULL
              AND created_at > NOW() - INTERVAL '3 hours'
              AND (sentiment_label IS NULL OR sentiment_label != '_clean_filtered')
              AND (
                sentiment_label IS NULL
                OR headline_ko IS NULL    OR headline_ko    !~ '[가-힣ㄱ-ㅎㅏ-ㅣ]'
                OR summary_3lines_ko IS NULL OR summary_3lines_ko::text !~ '[가-힣ㄱ-ㅎㅏ-ㅣ]'
                OR xai_ko IS NULL         OR xai_ko::text   !~ '[가-힣ㄱ-ㅎㅏ-ㅣ]'
              )
            ORDER BY published_at DESC
            LIMIT :#{#pageable.pageSize}
            """, nativeQuery = true)
    List<NewsArticle> findUnanalyzed(Pageable pageable);

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
