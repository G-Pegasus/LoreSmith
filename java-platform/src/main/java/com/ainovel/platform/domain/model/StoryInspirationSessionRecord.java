package com.ainovel.platform.domain.model;

import java.time.Instant;

public record StoryInspirationSessionRecord(
        String sessionId,
        String memorySummary,
        Instant createdAt,
        Instant updatedAt
) {}
