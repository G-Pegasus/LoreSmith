package com.ainovel.platform.interfaces.dto;

import java.util.List;

public record InspirationSessionResponse(
        String sessionId,
        String memorySummary,
        List<InspirationMessageResponse> messages,
        String updatedAt
) {}
