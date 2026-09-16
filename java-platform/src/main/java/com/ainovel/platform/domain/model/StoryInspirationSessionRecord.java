package com.ainovel.platform.domain.model;

import java.time.Instant;

/**
 * 灵感对话会话。
 *
 * <p>{@code draftSettings} / {@code confirmedSettings} 是 {@code InspirationSettingsResponse} 的原始
 * JSON 文本，仓储层不做解析，避免把设定契约下沉到基础设施层。</p>
 */
public record StoryInspirationSessionRecord(
        String sessionId,
        String memorySummary,
        String draftSettings,
        int draftRevision,
        String draftSourceMessageId,
        String confirmedSettings,
        int confirmedRevision,
        Instant createdAt,
        Instant updatedAt
) {}
