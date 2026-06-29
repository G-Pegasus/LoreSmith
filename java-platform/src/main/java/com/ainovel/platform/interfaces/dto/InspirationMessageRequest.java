package com.ainovel.platform.interfaces.dto;

import jakarta.validation.constraints.NotBlank;

public record InspirationMessageRequest(
        @NotBlank(message = "content is required") String content
) {}
