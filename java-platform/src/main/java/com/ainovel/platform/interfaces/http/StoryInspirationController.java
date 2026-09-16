package com.ainovel.platform.interfaces.http;

import com.ainovel.platform.application.StoryInspirationApplicationService;
import com.ainovel.platform.interfaces.dto.ApiResponse;
import com.ainovel.platform.interfaces.dto.InspirationMessageRequest;
import com.ainovel.platform.interfaces.dto.InspirationSessionResponse;
import com.ainovel.platform.interfaces.dto.InspirationSettingsConfirmRequest;
import java.util.Map;
import jakarta.validation.Valid;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
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

    /**
     * 确认整张设定草稿。版本不匹配或不完整时返回 409 STALE_DRAFT。
     * 确认只是把快照抄进表单，落库仍走「保存并开始创作」那条既有链路。
     */
    @PostMapping("/{sessionId}/settings/confirm")
    public ApiResponse<InspirationSessionResponse> confirm(
            @PathVariable String sessionId,
            @Valid @RequestBody InspirationSettingsConfirmRequest request
    ) {
        return ApiResponse.ok(service.confirmSettings(sessionId, request.expectedDraftRevision()));
    }

    /**
     * 删除整个会话（含消息与设定快照），供前端「重置对话」清理旧会话用。
     *
     * <p>幂等：删一个不存在或已删的会话同样返回成功，前端可以放心重试。
     * 前端界面的清空靠轮换 sessionId + 组件重挂载完成，这个端点只负责把库里那行抹掉。</p>
     */
    @DeleteMapping("/{sessionId}")
    public ApiResponse<Map<String, Boolean>> delete(@PathVariable String sessionId) {
        return ApiResponse.ok(Map.of("deleted", service.deleteSession(sessionId)));
    }
}
