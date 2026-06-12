package com.finswipe.domain.repository;

import com.finswipe.domain.entity.ChatMessage;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

import java.util.List;
import java.util.UUID;

public interface ChatMessageRepository extends JpaRepository<ChatMessage, UUID> {

    @Query("SELECT m FROM ChatMessage m WHERE m.userId = :userId ORDER BY m.createdAt DESC")
    List<ChatMessage> findRecentByUserId(@Param("userId") UUID userId, Pageable pageable);
}
