package com.ainovel.platform.domain.model;

import java.time.Instant;

public record StoryInspirationMessageRecord(
        String messageId,
        String sessionId,
        String role,
        String content,
        Instant createdAt
) {}
