package com.ainovel.platform.interfaces.http;

import com.ainovel.platform.application.StoryInspirationApplicationService;
import com.ainovel.platform.interfaces.dto.ApiResponse;
import com.ainovel.platform.interfaces.dto.InspirationMessageRequest;
import com.ainovel.platform.interfaces.dto.InspirationSessionResponse;
import jakarta.validation.Valid;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

@RestController
@RequestMapping("/api/v1/inspiration-sessions")
public class StoryInspirationController {
    private final StoryInspirationApplicationService service;

    public StoryInspirationController(StoryInspirationApplicationService service) {
        this.service = service;
    }

    @GetMapping("/{sessionId}")
    public ApiResponse<InspirationSessionResponse> get(@PathVariable String sessionId) {
        return ApiResponse.ok(service.getSession(sessionId));
    }

    @PostMapping(value = "/{sessionId}/messages/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public ResponseEntity<SseEmitter> stream(
            @PathVariable String sessionId,
            @Valid @RequestBody InspirationMessageRequest request
    ) {
        return ResponseEntity.ok()
                .header(HttpHeaders.CACHE_CONTROL, "no-cache")
                .header("X-Accel-Buffering", "no")
                .contentType(MediaType.TEXT_EVENT_STREAM)
                .body(service.streamMessage(sessionId, request));
    }
}
