package com.ainovel.platform.interfaces.http;

import com.ainovel.platform.domain.exception.StaleDraftException;
import com.ainovel.platform.interfaces.dto.ErrorResponse;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
public class ApiExceptionHandler {
    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<ErrorResponse> handleValidation(MethodArgumentNotValidException ex) {
        return ResponseEntity.badRequest().body(new ErrorResponse(
                "INVALID_ARGUMENT",
                ex.getBindingResult().getFieldError() != null ? ex.getBindingResult().getFieldError().getDefaultMessage() : "validation failed"
        ));
    }

    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseEntity<ErrorResponse> handleIllegalArgument(IllegalArgumentException ex) {
        return ResponseEntity.badRequest().body(new ErrorResponse(
                "INVALID_ARGUMENT",
                ex.getMessage() == null ? "invalid argument" : ex.getMessage()
        ));
    }

    /** 设定确认单已过期：草稿版本不匹配，前端应改用最新的确认单。 */
    @ExceptionHandler(StaleDraftException.class)
    public ResponseEntity<ErrorResponse> handleStaleDraft(StaleDraftException ex) {
        return ResponseEntity.status(HttpStatus.CONFLICT).body(new ErrorResponse(
                "STALE_DRAFT",
                ex.getMessage() == null ? "stale draft" : ex.getMessage()
        ));
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<ErrorResponse> handleGeneric(Exception ex) {
        return ResponseEntity.status(HttpStatus.BAD_GATEWAY).body(new ErrorResponse(
                "UPSTREAM_ERROR",
                ex.getMessage() == null ? "upstream error" : ex.getMessage()
        ));
    }
}
