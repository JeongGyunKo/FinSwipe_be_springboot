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

    // 최신 기사 페이징 (published_at 내림차순)
    Page<NewsArticle> findAllByOrderByPublishedAtDesc(Pageable pageable);

    // 특정 티커들을 포함한 기사 ID 목록 조회 (native → JPQL 2단계로 StringListType 보호)
    @Query(value = "SELECT id FROM news_articles WHERE tickers && CAST(:tickers AS text[]) ORDER BY published_at DESC LIMIT :limit OFFSET :offset",
            nativeQuery = true)
    List<java.util.UUID> findIdsByTickersOverlap(@Param("tickers") String tickers,
                                                 @Param("limit") int limit,
                                                 @Param("offset") int offset);

    @Query(value = "SELECT COUNT(*) FROM news_articles WHERE tickers && CAST(:tickers AS text[])",
            nativeQuery = true)
    long countByTickersOverlap(@Param("tickers") String tickers);

    // ID 목록으로 순서 보장하며 엔티티 조회 (JPQL → StringListType 정상 동작)
    @Query("SELECT a FROM NewsArticle a WHERE a.id IN :ids ORDER BY a.publishedAt DESC")
    List<NewsArticle> findByIdIn(@Param("ids") List<java.util.UUID> ids);

    // 미분석 기사 조회 — 30일 이내 기사만 (오래된 기사 무한 재처리 방지)
    @Query(value = """
            SELECT * FROM news_articles
            WHERE content IS NOT NULL
              AND published_at > NOW() - INTERVAL '30 days'
              AND (sentiment_label IS NULL OR sentiment_label != '_clean_filtered')
              AND (sentiment_label IS NULL OR summary_3lines_ko IS NULL OR headline_ko IS NULL OR xai_ko IS NULL)
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
