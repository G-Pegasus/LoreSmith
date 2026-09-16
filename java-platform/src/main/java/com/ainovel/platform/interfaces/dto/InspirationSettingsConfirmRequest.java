package com.ainovel.platform.interfaces.dto;

import jakarta.validation.constraints.NotNull;

/**
 * 确认单提交：{@code expectedDraftRevision} 是乐观校验凭据，与服务端当前草稿版本不一致时返回 409。
 */
public record InspirationSettingsConfirmRequest(
        @NotNull(message = "expectedDraftRevision is required") Integer expectedDraftRevision
) {}
