package com.finswipe.domain.repository;

import com.finswipe.domain.entity.TickerName;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;
import java.util.Optional;

public interface TickerNameRepository extends JpaRepository<TickerName, String> {

    @Query("SELECT t FROM TickerName t WHERE t.delistedAt IS NULL")
    List<TickerName> findAll();

    // 영문/한글 이름으로 검색 (대소문자 무시) — LIKE 특수문자 이스케이프는 호출 전 처리
    @Query("SELECT t FROM TickerName t WHERE t.delistedAt IS NULL AND (LOWER(t.corp) LIKE LOWER(CONCAT('%', :query, '%')) ESCAPE '\\' OR LOWER(t.ko) LIKE LOWER(CONCAT('%', :query, '%')) ESCAPE '\\' OR LOWER(t.ticker) LIKE LOWER(CONCAT('%', :query, '%')) ESCAPE '\\')")
    List<TickerName> searchByName(@Param("query") String query);

    Optional<TickerName> findByTicker(String ticker);

    @Query("SELECT t.ticker FROM TickerName t WHERE t.delistedAt IS NULL")
    List<String> findAllTickers();
}
