package com.ainovel.platform.application;

import com.ainovel.platform.domain.model.StoryInspirationMessageRecord;
import com.ainovel.platform.domain.model.StoryInspirationSessionRecord;
import com.ainovel.platform.infrastructure.repository.StoryInspirationRepository;
import com.ainovel.platform.interfaces.dto.InspirationMessageRequest;
import com.ainovel.platform.interfaces.dto.InspirationMessageResponse;
import com.ainovel.platform.interfaces.dto.InspirationSessionResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;

@Service
public class StoryInspirationApplicationService {
    private static final Logger LOGGER = LoggerFactory.getLogger(StoryInspirationApplicationService.class);
    private static final int RECENT_MESSAGE_LIMIT = 24;
    private static final int MEMORY_MAX_CHARS = 6000;
    private static final long STREAM_TIMEOUT_MILLIS = 180_000L;

    private final StoryInspirationRepository repository;
    private final InspirationAiClient aiClient;

    public StoryInspirationApplicationService(StoryInspirationRepository repository, InspirationAiClient aiClient) {
        this.repository = repository;
        this.aiClient = aiClient;
    }

    public InspirationSessionResponse getSession(String sessionId) {
        StoryInspirationSessionRecord session = ensureSession(sessionId);
        return toResponse(session, repository.listMessages(session.sessionId()));
    }

    private StoryInspirationSessionRecord ensureSession(String sessionId) {
        String cleanSessionId = sessionId == null ? "" : sessionId.trim();
        if (cleanSessionId.isBlank()) {
            throw new IllegalArgumentException("sessionId is required");
        }
        return repository.findSession(cleanSessionId)
                .orElseGet(() -> repository.upsertSession(cleanSessionId, "", Instant.now()));
    }

    private List<StoryInspirationMessageRecord> recent(List<StoryInspirationMessageRecord> messages) {
        if (messages.size() <= RECENT_MESSAGE_LIMIT) {
            return messages;
        }
        return messages.subList(messages.size() - RECENT_MESSAGE_LIMIT, messages.size());
    }

    private String buildMemorySummary(List<StoryInspirationMessageRecord> messages) {
        StringBuilder builder = new StringBuilder();
        builder.append("用户创作灵感长期记忆：\n");
        messages.stream()
                .filter(message -> "user".equals(message.role()))
                .forEach(message -> builder.append("- 用户补充：")
                        .append(compact(message.content(), 500))
                        .append('\n'));
        messages.stream()
                .filter(message -> "assistant".equals(message.role()))
                .reduce((first, second) -> second)
                .ifPresent(message -> builder.append("- 最近一次 AI 建议重点：")
                        .append(compact(message.content(), 900))
                        .append('\n'));
        return compact(builder.toString(), MEMORY_MAX_CHARS);
    }

    private String compact(String value, int maxChars) {
        String text = value == null ? "" : value.replaceAll("\\s+", " ").trim();
        if (text.length() <= maxChars) {
            return text;
        }
        return text.substring(0, Math.max(0, maxChars - 1)).trim() + "…";
    }

    private InspirationSessionResponse toResponse(StoryInspirationSessionRecord session, List<StoryInspirationMessageRecord> messages) {
        return new InspirationSessionResponse(
                session.sessionId(),
                session.memorySummary(),
                messages.stream().map(this::toMessageResponse).toList(),
                session.updatedAt().toString()
        );
    }

    public SseEmitter streamMessage(String sessionId, InspirationMessageRequest request) {
        String content = request.content() == null ? "" : request.content().trim();
        if (content.isBlank()) {
            throw new IllegalArgumentException("content is required");
        }

        SseEmitter emitter = new SseEmitter(STREAM_TIMEOUT_MILLIS);
        CompletableFuture.runAsync(() -> streamMessageInternal(sessionId, content, emitter));
        return emitter;
    }

    private void streamMessageInternal(String sessionId, String content, SseEmitter emitter) {
        try {
            StoryInspirationSessionRecord session = ensureSession(sessionId);
            Instant userTime = Instant.now();
            StoryInspirationMessageRecord userMessage = repository.saveMessage(new StoryInspirationMessageRecord(
                    "inmsg_" + UUID.randomUUID(),
                    session.sessionId(),
                    "user",
                    content,
                    userTime
            ));
            sendEvent(emitter, "user", toMessageResponse(userMessage));

            List<StoryInspirationMessageRecord> messagesAfterUser = repository.listMessages(session.sessionId());
            List<StoryInspirationMessageRecord> recentMessages = recent(messagesAfterUser);
            String assistantContent = aiClient.stream(session.memorySummary(), recentMessages, delta -> {
                try {
                    sendEvent(emitter, "delta", Map.of("delta", delta));
                } catch (IOException ex) {
                    throw new IllegalStateException("failed to send inspiration stream delta", ex);
                }
            });

            Instant assistantTime = Instant.now();
            repository.saveMessage(new StoryInspirationMessageRecord(
                    "inmsg_" + UUID.randomUUID(),
                    session.sessionId(),
                    "assistant",
                    assistantContent,
                    assistantTime
            ));

            List<StoryInspirationMessageRecord> allMessages = repository.listMessages(session.sessionId());
            StoryInspirationSessionRecord nextSession = repository.updateMemory(
                    session.sessionId(),
                    buildMemorySummary(allMessages),
                    Instant.now()
            );
            sendEvent(emitter, "done", toResponse(nextSession, allMessages));
            emitter.complete();
        } catch (Exception ex) {
            LOGGER.warn("inspiration stream failed: {}", ex.getMessage());
            try {
                sendEvent(emitter, "error", Map.of("message", "灵感对话暂时不可用，请稍后重试。"));
                emitter.complete();
            } catch (IOException ioException) {
                emitter.completeWithError(ioException);
            }
        }
    }

    private InspirationMessageResponse toMessageResponse(StoryInspirationMessageRecord message) {
        return new InspirationMessageResponse(
                message.messageId(),
                message.role(),
                message.content(),
                message.createdAt().toString()
        );
    }

    private void sendEvent(SseEmitter emitter, String eventName, Object data) throws IOException {
        synchronized (emitter) {
            emitter.send(SseEmitter.event().name(eventName).data(data));
        }
    }
}
