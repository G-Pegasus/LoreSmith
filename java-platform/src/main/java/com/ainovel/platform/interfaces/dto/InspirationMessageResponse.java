package com.ainovel.platform.interfaces.dto;

public record InspirationMessageResponse(
        String messageId,
        String role,
        String content,
        String createdAt
) {}
