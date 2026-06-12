package com.finswipe.dto.response;

import java.time.OffsetDateTime;
import java.util.UUID;

public record ChatMessageDto(
    UUID id,
    String role,
    String content,
    String ticker,
    UUID articleId,
    OffsetDateTime createdAt
) {}
