package com.ainovel.platform.application;

import com.ainovel.platform.domain.exception.StaleDraftException;
import com.ainovel.platform.domain.model.StoryInspirationMessageRecord;
import com.ainovel.platform.domain.model.StoryInspirationSessionRecord;
import com.ainovel.platform.infrastructure.repository.StoryInspirationRepository;
import com.ainovel.platform.interfaces.dto.InspirationMessageRequest;
import com.ainovel.platform.interfaces.dto.InspirationMessageResponse;
import com.ainovel.platform.interfaces.dto.InspirationSessionResponse;
import com.ainovel.platform.interfaces.dto.InspirationSettingsResponse;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;

@Service
public class StoryInspirationApplicationService {
    private static final Logger LOGGER = LoggerFactory.getLogger(StoryInspirationApplicationService.class);
    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper()
            .configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, false);

    private static final int RECENT_MESSAGE_LIMIT = 24;
    private static final int MEMORY_MAX_CHARS = 6000;
    private static final long STREAM_TIMEOUT_MILLIS = 180_000L;

    /** 抽取输入窗口：最近 4 轮对话（4 组 user + assistant）。用 24 条会淹掉当前意图。 */
    private static final int EXTRACT_MESSAGE_LIMIT = 8;
    private static final int EXTRACT_MESSAGE_MAX_CHARS = 1200;

    private static final String SLOT_TITLE = "作品标题";
    private static final String SLOT_WORLD_SETTING = "世界观设定";
    private static final String SLOT_CHARACTERS = "角色设定";
    private static final String SLOT_SYNOPSIS = "故事简介";

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

    /**
     * 删除整个会话：记忆摘要、草稿 / 确认快照随行删除，消息由 FK CASCADE 带走。
     *
     * <p>刻意<b>不走 {@link #ensureSession}</b>：那个方法查不到 id 会顺手建一行空会话，
     * 于是"删一个不存在或已删的会话"就会变成"先造一行再删掉"，既无意义又会污染日志。
     * 这里是重置操作的下游，必须幂等。</p>
     */
    public boolean deleteSession(String sessionId) {
        String cleanSessionId = sessionId == null ? "" : sessionId.trim();
        if (cleanSessionId.isBlank()) {
            throw new IllegalArgumentException("sessionId is required");
        }
        boolean removed = repository.deleteSession(cleanSessionId);
        if (!removed) {
            LOGGER.info("inspiration session already gone, nothing to delete: {}", cleanSessionId);
        }
        return removed;
    }

    /**
     * 确认整张设定草稿并填入工作台。只写 session 上的两个快照列，不写 store —— 表单仍是唯一提交入口。
     *
     * @param expectedDraftRevision 前端持有的草稿版本号，与服务端不一致时抛出 {@link StaleDraftException}
     */
    public InspirationSessionResponse confirmSettings(String sessionId, int expectedDraftRevision) {
        StoryInspirationSessionRecord session = ensureSession(sessionId);
        if (expectedDraftRevision != session.draftRevision()) {
            throw new StaleDraftException("设定已更新，请使用最新的确认单");
        }
        InspirationSettingsResponse draft = meaningfulDraft(session.draftSettings());
        if (!isFourSlotsComplete(draft)) {
            throw new StaleDraftException("当前没有可确认的完整设定草稿");
        }
        StoryInspirationSessionRecord updated = repository.updateConfirmed(
                session.sessionId(),
                session.draftSettings(),
                session.draftRevision(),
                Instant.now()
        );
        return toResponse(updated, repository.listMessages(session.sessionId()));
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
                session.updatedAt().toString(),
                parseSettings(session.draftSettings()),
                session.draftRevision(),
                session.confirmedRevision(),
                session.draftSourceMessageId(),
                parseSettings(session.confirmedSettings())
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
            String draftContext = buildDraftContext(parseSettings(session.draftSettings()));
            String assistantContent = aiClient.stream(
                    session.memorySummary(),
                    recent(messagesAfterUser),
                    draftContext,
                    delta -> {
                        try {
                            sendEvent(emitter, "delta", Map.of("delta", delta));
                        } catch (IOException ex) {
                            throw new IllegalStateException("failed to send inspiration stream delta", ex);
                        }
                    });

            StoryInspirationMessageRecord assistantMessage = repository.saveMessage(new StoryInspirationMessageRecord(
                    "inmsg_" + UUID.randomUUID(),
                    session.sessionId(),
                    "assistant",
                    assistantContent,
                    Instant.now()
            ));

            // 正文已经流完，接下来最多静默 extract 超时那么久 —— 先给前端一个明确信号，
            // 否则用户会以为本轮结束、再发一条，导致两条请求并发。
            sendEvent(emitter, "phase", Map.of("phase", "extracting"));
            updateDraftAfterTurn(session, assistantMessage);

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

    /**
     * 回合末抽取设定草稿并更新版本号与待确认卡指针。
     *
     * <p>任何异常都在这里被吞掉：抽取失败只意味着"本轮草稿不变、不出新卡"，必须保证 {@code done} 照常发出，
     * 也绝不能回退到 {@code emitFallback}（那段模板文案会被当成草稿写库）。</p>
     */
    private void updateDraftAfterTurn(StoryInspirationSessionRecord session, StoryInspirationMessageRecord assistantMessage) {
        try {
            InspirationSettingsResponse previous = meaningfulDraft(session.draftSettings());
            InspirationSettingsResponse extracted = aiClient.extractDraft(
                    previous == null ? null : writeSettings(previous),
                    extractWindow(repository.listMessages(session.sessionId()))
            );
            if (extracted == null) {
                LOGGER.info("inspiration draft extraction produced nothing, keeping current draft");
                return;
            }
            // 防呆：某个字段本轮没输出，就沿用上一版，避免 LLM 漏字段把已定内容清空 → 四槽位判定失败 → 卡片消失。
            InspirationSettingsResponse merged = mergeWithPrevious(previous, extracted);
            boolean changed = previous == null ? !isBlankDraft(merged) : !merged.equals(previous);
            if (previous == null && !changed) {
                return;
            }
            int draftRevision = changed ? session.draftRevision() + 1 : session.draftRevision();
            String draftSettings = changed ? writeSettings(merged) : session.draftSettings();

            boolean eligible = isFourSlotsComplete(merged) && draftRevision > session.confirmedRevision();
            String sourceMessageId = eligible
                    ? (changed ? assistantMessage.messageId() : session.draftSourceMessageId())
                    : null;

            repository.updateDraft(session.sessionId(), draftSettings, draftRevision, sourceMessageId, Instant.now());
        } catch (Exception ex) {
            LOGGER.warn("inspiration draft update skipped: {}", ex.getMessage());
        }
    }

    private List<StoryInspirationMessageRecord> extractWindow(List<StoryInspirationMessageRecord> messages) {
        int from = Math.max(0, messages.size() - EXTRACT_MESSAGE_LIMIT);
        return messages.subList(from, messages.size()).stream()
                .map(message -> new StoryInspirationMessageRecord(
                        message.messageId(),
                        message.sessionId(),
                        message.role(),
                        compact(message.content(), EXTRACT_MESSAGE_MAX_CHARS),
                        message.createdAt()
                ))
                .toList();
    }

    /** 把当前草稿拼成一段结构化状态注入主对话，让 AI 知道"齐到哪一步了"，不再重复追问已定项。 */
    private String buildDraftContext(InspirationSettingsResponse draft) {
        if (draft == null || isBlankDraft(draft)) {
            return "";
        }
        List<String> missing = new ArrayList<>();
        if (isBlank(draft.title())) {
            missing.add(SLOT_TITLE);
        }
        if (isBlank(draft.worldSetting())) {
            missing.add(SLOT_WORLD_SETTING);
        }
        if (draft.characters() == null || draft.characters().isEmpty()) {
            missing.add(SLOT_CHARACTERS);
        }
        if (isBlank(draft.synopsis())) {
            missing.add(SLOT_SYNOPSIS);
        }
        return """
                当前设定草稿（已确定的内容，不要重复询问）：
                %s

                尚未确定的项：%s
                """.formatted(writeSettings(draft), missing.isEmpty() ? "无（四件套已齐，请提示用户可以填入工作台）" : String.join("、", missing));
    }

    /**
     * 四槽位判定 —— 出卡的充要条件之一，纯代码判断，零模型输出、零关键词表。
     * 另一半是 {@code draftRevision > confirmedRevision}（防止刚确认完又弹一次）。
     */
    private boolean isFourSlotsComplete(InspirationSettingsResponse draft) {
        return draft != null
                && !isBlank(draft.title())
                && !isBlank(draft.worldSetting())
                && draft.characters() != null
                && !draft.characters().isEmpty()
                && !isBlank(draft.synopsis());
    }

    private boolean isBlankDraft(InspirationSettingsResponse draft) {
        return draft == null
                || (isBlank(draft.title())
                && isBlank(draft.worldSetting())
                && isBlank(draft.synopsis())
                && (draft.characters() == null || draft.characters().isEmpty()));
    }

    /** 全空草稿视同"还没有草稿"，让 {@code previous == null} 这一个判断就够用。 */
    private InspirationSettingsResponse meaningfulDraft(String draftSettings) {
        InspirationSettingsResponse parsed = parseSettings(draftSettings);
        return isBlankDraft(parsed) ? null : parsed;
    }

    private InspirationSettingsResponse mergeWithPrevious(
            InspirationSettingsResponse previous,
            InspirationSettingsResponse next
    ) {
        if (previous == null) {
            return next;
        }
        return new InspirationSettingsResponse(
                prefer(next.title(), previous.title()),
                prefer(next.worldSetting(), previous.worldSetting()),
                next.characters() == null || next.characters().isEmpty() ? previous.characters() : next.characters(),
                prefer(next.synopsis(), previous.synopsis())
        );
    }

    private String prefer(String value, String fallback) {
        return isBlank(value) ? fallback : value;
    }

    private boolean isBlank(String value) {
        return value == null || value.isBlank();
    }

    private InspirationSettingsResponse parseSettings(String settingsJson) {
        if (settingsJson == null || settingsJson.isBlank()) {
            return null;
        }
        try {
            return OBJECT_MAPPER.readValue(settingsJson, InspirationSettingsResponse.class);
        } catch (JsonProcessingException ex) {
            LOGGER.warn("failed to parse inspiration settings: {}", ex.getMessage());
            return null;
        }
    }

    private String writeSettings(InspirationSettingsResponse settings) {
        if (settings == null) {
            return null;
        }
        try {
            return OBJECT_MAPPER.writeValueAsString(settings);
        } catch (JsonProcessingException ex) {
            throw new IllegalStateException("failed to serialize inspiration settings", ex);
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
