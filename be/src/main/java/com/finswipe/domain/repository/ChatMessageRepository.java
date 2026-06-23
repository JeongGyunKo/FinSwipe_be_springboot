package com.finswipe.domain.repository;

import com.finswipe.domain.entity.ChatMessage;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;
import java.util.UUID;

public interface ChatMessageRepository extends JpaRepository<ChatMessage, UUID> {

    @Query("SELECT m FROM ChatMessage m WHERE m.userId = :userId ORDER BY m.createdAt DESC")
    List<ChatMessage> findRecentByUserId(@Param("userId") UUID userId, Pageable pageable);

    @Modifying
    @Query("UPDATE ChatMessage m SET m.isRead = true WHERE m.userId = :userId AND m.isRead = false")
    void markAllReadByUserId(@Param("userId") UUID userId);

    // 미읽음 감성 알림 개수 — "N개의 주요한 뉴스가 있어요" 안내·뱃지용
    @Query("SELECT COUNT(m) FROM ChatMessage m WHERE m.userId = :userId AND m.role = 'alert' AND m.isRead = false")
    long countUnreadAlerts(@Param("userId") UUID userId);
}
