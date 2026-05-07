package com.finswipe.domain.repository;

import com.finswipe.domain.entity.TickerName;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;
import java.util.Optional;

public interface TickerNameRepository extends JpaRepository<TickerName, String> {

    // 영문/한글 이름으로 검색 (대소문자 무시)
    @Query("SELECT t FROM TickerName t WHERE LOWER(t.corp) LIKE LOWER(CONCAT('%', :query, '%')) OR LOWER(t.ko) LIKE LOWER(CONCAT('%', :query, '%')) OR LOWER(t.ticker) LIKE LOWER(CONCAT('%', :query, '%'))")
    List<TickerName> searchByName(@Param("query") String query);

    Optional<TickerName> findByTicker(String ticker);

    @Query("SELECT t.ticker FROM TickerName t")
    List<String> findAllTickers();
}
