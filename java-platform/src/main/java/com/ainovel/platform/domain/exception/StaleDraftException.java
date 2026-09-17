package com.ainovel.platform.domain.exception;

/**
 * 设定确认单已过期或当前不可确认（草稿版本不匹配 / 草稿不完整）。由 HTTP 层映射为 409 STALE_DRAFT。
 */
public class StaleDraftException extends RuntimeException {
    public StaleDraftException(String message) {
        super(message);
    }
}
