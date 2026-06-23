package com.finswipe.dto.response;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.time.OffsetDateTime;
import java.util.UUID;

public record ChatMessageDto(
    UUID id,
    String role,
    String content,
    String ticker,
    UUID articleId,
    OffsetDateTime createdAt,
    @JsonProperty("is_read") boolean isRead
) {}
