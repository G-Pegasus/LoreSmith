package com.ainovel.platform.application;

import com.ainovel.platform.domain.model.StoryInspirationMessageRecord;
import com.ainovel.platform.interfaces.dto.InspirationSettingsResponse;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.env.Environment;
import org.springframework.core.io.buffer.DataBuffer;
import org.springframework.core.io.buffer.DataBufferUtils;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Consumer;

@Component
public class InspirationAiClient {
    private static final Logger LOGGER = LoggerFactory.getLogger(InspirationAiClient.class);
    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper()
            .configure(DeserializationFeature.FAIL_ON_UNKNOWN_PROPERTIES, false);
    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {};

    private static final double MAIN_TEMPERATURE = 0.78;
    private static final double EXTRACT_TEMPERATURE = 0.2;
    /**
     * 抽取默认超时。实测（deepseek 系推理模型 + {@code thinking: disabled}）单次约 2-4 秒，
     * 取 15 秒作为安全边界；调试期可用 AINOVEL_EXTRACT_TIMEOUT_MS 调短。
     */
    private static final long DEFAULT_EXTRACT_TIMEOUT_MILLIS = 15_000L;

    /**
     * 主对话提示词：围绕"设定四件套"推进，不再每轮输出"可直接填入的精炼设定"。
     * 那段总结会和确认单形成两个来源，"每轮都追问"则让"问完"永不可达。
     */
    public static final String SYSTEM_PROMPT = """
            你是“墨韵AI”的小说创作灵感顾问，负责帮用户把作品构思打磨到“可以直接开写”。

            你要和用户一起敲定的四件事（称为“设定四件套”）：
            1. 作品标题
            2. 世界观设定
            3. 角色设定（至少一个主要角色：姓名 + 定位 + 描述）
            4. 故事简介

            工作方式：
            - 每轮先回应用户刚说的内容，点出其中有价值的钩子，再推进“四件套”里还没定下来的部分。
            - 只针对“尚未确定”的项追问，一次最多问 2 个问题。已经确定的项不要重复询问。
            - 如果用户的新说法与已确定的设定冲突，直接指出冲突，请用户确认取舍。
            - 不要在回复里写“可直接填入新建作品页的精炼设定”这类总结段落 —— 系统会自动把设定整理成确认单。
            - 当四件套全部确定后，明确告诉用户“设定已完整，可以填入工作台了”，不要再提新问题。

            设定质量要求：
            - 标题短而有钩子，避免《XX之路》《XX纪》这类空泛命名。
            - 世界观要说清时代/地点/背景，并包含一条会反复制造麻烦的规则（身份限制、资源稀缺、契约代价、舆论审判等）。
            - 角色要有明确的欲望与代价，不要只写身份标签。
            - 故事简介要说清“谁、在什么处境下、要做什么、最大的阻力是什么”。
            - 保护用户原创性：不要套模板替换名词，不要泛泛而谈。

            记忆规则：
            - 你会收到“长期记忆摘要”“当前设定草稿”和最近多轮对话。
            - “当前设定草稿”是系统整理出的已确定设定，以它为准：不要重复询问，也不要自相矛盾。
            - 当用户修改设定时，以最新说法为准，并指出哪些旧建议需要同步调整。

            风格要求：
            - 中文输出，结构清晰，标题短，建议具体。
            - 避免“命运齿轮开始转动”“前所未有的挑战”等 AI 腔套话。
            - 不输出安全无关免责声明。
            """;

    /**
     * 抽取提示词：把对话蒸馏成结构化设定草稿。只输出 JSON，不输出任何解释。
     *
     * <p>措辞里刻意强调"宁可写得短，也不要留空"：抽取结果直接驱动四槽位判定，任何一项被模型
     * 顺手留空都会让确认单不出卡。实测关掉思维链后模型会偷懒漏字段，这条约束是必需的。</p>
     */
    public static final String EXTRACT_PROMPT = """
            你是小说设定抽取器。从对话中抽取这部作品的“设定四件套”，输出 JSON。

            四个字段的含义：
            - title：作品标题。
            - worldSetting：世界观设定，说清时代/地点/背景、核心规则与主要冲突来源。
            - characters：角色数组，每项 { "name": 姓名, "role": 定位, "description": 描述 }。role 用“主角”“配角”“反派”这类短标签；description 说清身份、欲望与代价。
            - synopsis：故事简介，说清谁、在什么处境下、要做什么、最大阻力是什么。

            硬性要求：
            1. 只输出 JSON，不要解释，不要 Markdown 代码块。
            2. 输出“全量草稿”：上一版草稿中已经确定、且本轮对话没有修改的字段，必须原样照抄，禁止改写、精简或重新润色。
            3. **宁可写得短，也不要留空**。只要对话里出现过能判断出该字段的信息，就必须写出来；信息不完整时按已有内容如实写，等后续轮次再补，不要为了凑字数编造，也不要因为“还不够丰满”就留空。
            4. worldSetting 只要对话提到时代、地点、背景或任何一条世界规则，就必须输出；synopsis 只要求说清主线，不要求完整。
            5. 只有整段对话里确实完全没有涉及某个字段时，才输出空字符串或空数组。
            6. synopsis 必须来自对话内容 —— 禁止照抄任何默认文案或占位文案。
            7. 不要输出思考过程。

            输出格式：
            { "draft": { "title": "", "worldSetting": "", "characters": [], "synopsis": "" } }
            """;

    private final WebClient webClient;
    private final Environment environment;

    public InspirationAiClient(WebClient.Builder builder, Environment environment) {
        this.webClient = builder.build();
        this.environment = environment;
    }

    public String stream(
            String memorySummary,
            List<StoryInspirationMessageRecord> recentMessages,
            String draftContext,
            Consumer<String> deltaConsumer
    ) {
        LlmConfig config = loadDevConfig();
        if (config.apiKey().isBlank()) {
            return emitFallback(memorySummary, recentMessages, deltaConsumer);
        }

        StringBuilder assistantContent = new StringBuilder();
        StringBuilder lineBuffer = new StringBuilder();
        try {
            Map<String, Object> payload = new LinkedHashMap<>();
            payload.put("model", config.model());
            payload.put("temperature", MAIN_TEMPERATURE);
            payload.put("stream", true);
            payload.put("messages", buildMessages(memorySummary, recentMessages, draftContext));

            webClient.post()
                    .uri(trimTrailingSlash(config.baseUrl()) + "/chat/completions")
                    .header(HttpHeaders.AUTHORIZATION, "Bearer " + config.apiKey())
                    .accept(MediaType.TEXT_EVENT_STREAM)
                    .bodyValue(payload)
                    .retrieve()
                    .bodyToFlux(DataBuffer.class)
                    .timeout(Duration.ofSeconds(effectiveTimeoutSeconds()))
                    .doOnNext(buffer -> {
                        String chunk = StandardCharsets.UTF_8.decode(buffer.asByteBuffer()).toString();
                        DataBufferUtils.release(buffer);
                        processStreamChunk(chunk, lineBuffer, assistantContent, deltaConsumer);
                    })
                    .blockLast();

            processStreamLine(lineBuffer.toString(), assistantContent, deltaConsumer);
            String text = assistantContent.toString().trim();
            if (text.isBlank()) {
                throw new IllegalStateException("AI stream content is empty");
            }
            return text;
        } catch (RuntimeException ex) {
            LOGGER.warn("inspiration AI stream request failed, falling back to local response: {}", ex.getMessage());
            return emitFallback(memorySummary, recentMessages, deltaConsumer);
        }
    }

    /**
     * 从最近几轮对话中抽取设定草稿。非流式、低温度、关闭思维链、带硬超时。
     *
     * <p><b>为什么必须关闭思维链</b>：抽取本质上只是把对话内容搬运成 JSON，不需要推理。
     * 实测推理模型在开启思维链时，一次抽取会额外生成 1400+ 个 reasoning token，
     * 耗时 30-76 秒 —— 而 {@code done} 事件压在抽取之后，这段等待会直接变成用户可见的卡顿。
     * 关闭后回落到 2-4 秒。可用 {@code dev_config.json} 的 {@code extract.disable_thinking} 关掉。</p>
     *
     * <p><b>失败即返回 null，绝不走 {@link #emitFallback}</b>：那段固定模板文案一旦被当作草稿解析就是垃圾写库。
     * 调用方必须把 null 视为“本轮跳过抽取”，并保证 {@code done} 事件照常发出。</p>
     *
     * @param currentDraftJson 上一版草稿 JSON，可为 null / 空
     * @return 抽取结果；失败或超时返回 null
     */
    public InspirationSettingsResponse extractDraft(
            String currentDraftJson,
            List<StoryInspirationMessageRecord> recentMessages
    ) {
        ExtractOptions options = loadExtractOptions();
        LlmConfig config = options.config();
        if (config.apiKey().isBlank()) {
            return null;
        }
        try {
            Map<String, Object> payload = new LinkedHashMap<>();
            payload.put("model", config.model());
            payload.put("temperature", EXTRACT_TEMPERATURE);
            payload.put("stream", false);
            if (options.disableThinking()) {
                payload.put("thinking", Map.of("type", "disabled"));
            }
            payload.put("messages", List.of(
                    Map.of("role", "system", "content", EXTRACT_PROMPT),
                    Map.of("role", "user", "content", buildExtractInput(currentDraftJson, recentMessages))
            ));

            String body = webClient.post()
                    .uri(trimTrailingSlash(config.baseUrl()) + "/chat/completions")
                    .header(HttpHeaders.AUTHORIZATION, "Bearer " + config.apiKey())
                    .accept(MediaType.APPLICATION_JSON)
                    .bodyValue(payload)
                    .retrieve()
                    .bodyToMono(String.class)
                    .timeout(Duration.ofMillis(options.timeoutMillis()))
                    .block();

            return parseExtractResponse(body);
        } catch (RuntimeException ex) {
            LOGGER.warn("inspiration draft extraction skipped: {}", ex.getMessage());
            return null;
        }
    }

    private String buildExtractInput(String currentDraftJson, List<StoryInspirationMessageRecord> recentMessages) {
        StringBuilder builder = new StringBuilder();
        builder.append("当前草稿（上一版）：\n");
        builder.append(currentDraftJson == null || currentDraftJson.isBlank() ? "（还没有草稿）" : currentDraftJson);
        builder.append("\n\n最近对话：\n");
        if (recentMessages == null || recentMessages.isEmpty()) {
            builder.append("（暂无）\n");
        } else {
            recentMessages.forEach(message -> builder
                    .append("user".equals(message.role()) ? "用户：" : "AI：")
                    .append(message.content())
                    .append('\n'));
        }
        return builder.toString();
    }

    @SuppressWarnings("unchecked")
    private InspirationSettingsResponse parseExtractResponse(String body) {
        if (body == null || body.isBlank()) {
            return null;
        }
        try {
            Map<String, Object> root = OBJECT_MAPPER.readValue(body, MAP_TYPE);
            Object choices = root.get("choices");
            if (!(choices instanceof List<?> list) || list.isEmpty() || !(list.getFirst() instanceof Map<?, ?> first)) {
                return null;
            }
            String content = null;
            Object message = first.get("message");
            if (message instanceof Map<?, ?> messageMap) {
                content = messageMap.get("content") == null ? null : String.valueOf(messageMap.get("content"));
            }
            if (content == null && first.get("text") != null) {
                content = String.valueOf(first.get("text"));
            }
            String json = extractJsonObject(content);
            if (json.isBlank()) {
                LOGGER.warn("inspiration draft extraction returned no JSON object");
                return null;
            }
            Map<String, Object> parsed = OBJECT_MAPPER.readValue(json, MAP_TYPE);
            Object draftNode = parsed.get("draft");
            if (!(draftNode instanceof Map<?, ?>)) {
                // 容错：模型直接把草稿吐在顶层
                draftNode = parsed;
            }
            InspirationSettingsResponse settings = OBJECT_MAPPER.convertValue(draftNode, InspirationSettingsResponse.class);
            return normalize(settings);
        } catch (IOException | IllegalArgumentException ex) {
            LOGGER.warn("inspiration draft extraction response is not parsable: {}", ex.getMessage());
            return null;
        }
    }

    private String extractJsonObject(String text) {
        if (text == null) {
            return "";
        }
        int start = text.indexOf('{');
        int end = text.lastIndexOf('}');
        if (start < 0 || end <= start) {
            return "";
        }
        return text.substring(start, end + 1);
    }

    /** 去掉空白、丢掉没有名字的角色，避免"空壳角色"把四槽位判定顶成齐备。 */
    private InspirationSettingsResponse normalize(InspirationSettingsResponse settings) {
        if (settings == null) {
            return null;
        }
        List<InspirationSettingsResponse.CharacterSetting> characters = settings.characters() == null
                ? List.of()
                : settings.characters().stream()
                        .filter(character -> character != null && !isBlank(character.name()))
                        .map(character -> new InspirationSettingsResponse.CharacterSetting(
                                character.name().trim(),
                                trimToEmpty(character.role()),
                                trimToEmpty(character.description())
                        ))
                        .toList();
        return new InspirationSettingsResponse(
                trimToEmpty(settings.title()),
                trimToEmpty(settings.worldSetting()),
                characters,
                trimToEmpty(settings.synopsis())
        );
    }

    private String trimToEmpty(String value) {
        return value == null ? "" : value.trim();
    }

    private boolean isBlank(String value) {
        return value == null || value.isBlank();
    }

    private List<Map<String, String>> buildMessages(
            String memorySummary,
            List<StoryInspirationMessageRecord> recentMessages,
            String draftContext
    ) {
        List<Map<String, String>> messages = new ArrayList<>();
        messages.add(Map.of("role", "system", "content", SYSTEM_PROMPT));
        if (memorySummary != null && !memorySummary.isBlank()) {
            messages.add(Map.of("role", "system", "content", "长期记忆摘要：\n" + memorySummary));
        }
        if (draftContext != null && !draftContext.isBlank()) {
            messages.add(Map.of("role", "system", "content", draftContext));
        }
        recentMessages.forEach(message -> messages.add(Map.of(
                "role", message.role(),
                "content", message.content()
        )));
        return messages;
    }

    private String fallback(String memorySummary, List<StoryInspirationMessageRecord> recentMessages) {
        String latestUser = recentMessages.stream()
                .filter(message -> "user".equals(message.role()))
                .reduce((first, second) -> second)
                .map(StoryInspirationMessageRecord::content)
                .orElse("我想写一部新的长篇小说。");
        String remembered = memorySummary == null || memorySummary.isBlank()
                ? "目前还没有稳定设定。"
                : memorySummary;
        return """
                ## 我理解到的创作目标
                你当前想围绕“%s”继续扩展作品设定。现有记忆显示：%s

                ## 设定拓展
                - 先确定主角最想得到什么，以及得到它必须付出的代价。
                - 给世界观增加一条会反复制造麻烦的规则，例如身份限制、资源稀缺、契约代价或舆论审判。
                - 让反派或阻力方拥有合理目标，不只是阻止主角，而是与主角争夺同一个稀缺结果。

                ## 追问
                - 主角最不能失去的东西是什么？
                - 这个世界最核心、最不可违背的规则是什么？
                - 你希望读者在前三章主要感受到爽感、悬疑、心疼，还是暧昧张力？
                """.formatted(latestUser, remembered);
    }

    private String emitFallback(String memorySummary, List<StoryInspirationMessageRecord> recentMessages, Consumer<String> deltaConsumer) {
        String text = fallback(memorySummary, recentMessages);
        emitDelta(text, deltaConsumer);
        return text;
    }

    private void emitDelta(String delta, Consumer<String> deltaConsumer) {
        if (delta == null || delta.isEmpty()) {
            return;
        }
        int chunkSize = 8;
        for (int start = 0; start < delta.length(); start += chunkSize) {
            deltaConsumer.accept(delta.substring(start, Math.min(delta.length(), start + chunkSize)));
            sleepQuietly(35);
        }
    }

    private void sleepQuietly(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt();
        }
    }

    private void processStreamChunk(
            String chunk,
            StringBuilder lineBuffer,
            StringBuilder assistantContent,
            Consumer<String> deltaConsumer
    ) {
        if (chunk == null || chunk.isBlank()) {
            return;
        }
        lineBuffer.append(chunk);
        int lineEnd;
        while ((lineEnd = indexOfLineEnd(lineBuffer)) >= 0) {
            String line = lineBuffer.substring(0, lineEnd);
            int removeUntil = lineEnd + 1;
            if (removeUntil < lineBuffer.length() && lineBuffer.charAt(lineEnd) == '\r' && lineBuffer.charAt(removeUntil) == '\n') {
                removeUntil++;
            }
            lineBuffer.delete(0, removeUntil);
            processStreamLine(line, assistantContent, deltaConsumer);
        }
    }

    private int indexOfLineEnd(StringBuilder builder) {
        int newline = builder.indexOf("\n");
        int carriageReturn = builder.indexOf("\r");
        if (newline < 0) {
            return carriageReturn;
        }
        if (carriageReturn < 0) {
            return newline;
        }
        return Math.min(newline, carriageReturn);
    }

    private void processStreamLine(String rawLine, StringBuilder assistantContent, Consumer<String> deltaConsumer) {
        String line = rawLine == null ? "" : rawLine.trim();
        if (line.isBlank() || line.startsWith(":")) {
            return;
        }
        String data = line.startsWith("data:") ? line.substring(5).trim() : line;
        if (data.isBlank() || "[DONE]".equals(data)) {
            return;
        }
        try {
            Map<String, Object> event = OBJECT_MAPPER.readValue(data, MAP_TYPE);
            String delta = extractStreamDelta(event);
            if (delta.isEmpty()) {
                return;
            }
            assistantContent.append(delta);
            emitDelta(delta, deltaConsumer);
        } catch (IOException ex) {
            LOGGER.debug("ignored invalid inspiration stream chunk: {}", data);
        }
    }

    private String extractStreamDelta(Map<String, Object> event) {
        Object choices = event.get("choices");
        if (!(choices instanceof List<?> list) || list.isEmpty()) {
            return "";
        }
        Object first = list.getFirst();
        if (!(first instanceof Map<?, ?> firstMap)) {
            return "";
        }
        Object delta = firstMap.get("delta");
        if (delta instanceof Map<?, ?> deltaMap) {
            Object content = deltaMap.get("content");
            return content == null ? "" : String.valueOf(content);
        }
        Object message = firstMap.get("message");
        if (message instanceof Map<?, ?> messageMap) {
            Object content = messageMap.get("content");
            return content == null ? "" : String.valueOf(content);
        }
        Object text = firstMap.get("text");
        return text == null ? "" : String.valueOf(text);
    }

    private String readConfig(String envName, String propertyName, String fallback) {
        String envValue = environment.getProperty(envName, "");
        if (envValue != null && !envValue.isBlank()) {
            return envValue.trim();
        }
        return environment.getProperty(propertyName, fallback).trim();
    }

    private long effectiveTimeoutSeconds() {
        String raw = environment.getProperty("AINOVEL_HTTP_TIMEOUT", "").trim();
        if (raw.isBlank()) {
            return 120;
        }
        try {
            long value = Math.round(Double.parseDouble(raw));
            return Math.max(10, value);
        } catch (NumberFormatException ex) {
            return 120;
        }
    }

    /**
     * 抽取调用的三个旋钮。默认全部可跑，允许通过 {@code dev_config.json} 的 {@code extract} 段或
     * 环境变量 {@code AINOVEL_EXTRACT_TIMEOUT_MS} 覆盖 —— 不改配置也能工作，是刻意的。
     */
    private ExtractOptions loadExtractOptions() {
        LlmConfig main = loadDevConfig();
        String model = main.model();
        boolean disableThinking = true;
        long timeoutMillis = envExtractTimeoutOrDefault();

        Map<String, Object> extract = readExtractBlock();
        if (extract != null) {
            String overrideModel = stringValue(extract.get("model"));
            if (!overrideModel.isBlank()) {
                model = overrideModel;
            }
            if (extract.get("disable_thinking") instanceof Boolean flag) {
                disableThinking = flag;
            }
            if (environment.getProperty("AINOVEL_EXTRACT_TIMEOUT_MS", "").isBlank()) {
                Object rawTimeout = extract.get("timeout_ms");
                if (rawTimeout != null) {
                    try {
                        timeoutMillis = Math.max(1, Math.round(Double.parseDouble(String.valueOf(rawTimeout).trim())));
                    } catch (NumberFormatException ex) {
                        LOGGER.warn("ignored invalid extract.timeout_ms: {}", rawTimeout);
                    }
                }
            }
        }
        return new ExtractOptions(new LlmConfig(main.apiKey(), model, main.baseUrl()), disableThinking, timeoutMillis);
    }

    private long envExtractTimeoutOrDefault() {
        String raw = environment.getProperty("AINOVEL_EXTRACT_TIMEOUT_MS", "").trim();
        if (raw.isBlank()) {
            return DEFAULT_EXTRACT_TIMEOUT_MILLIS;
        }
        try {
            return Math.max(1, Math.round(Double.parseDouble(raw)));
        } catch (NumberFormatException ex) {
            return DEFAULT_EXTRACT_TIMEOUT_MILLIS;
        }
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> readExtractBlock() {
        Path configPath = Path.of(readConfig("AINOVEL_CONFIG", "ainovel.config-path", "dev_config.json"));
        if (!Files.isRegularFile(configPath)) {
            return null;
        }
        try {
            Map<String, Object> root = OBJECT_MAPPER.readValue(configPath.toFile(), MAP_TYPE);
            Object extract = root.get("extract");
            return extract instanceof Map<?, ?> map ? (Map<String, Object>) map : null;
        } catch (IOException ex) {
            return null;
        }
    }

    @SuppressWarnings("unchecked")
    private LlmConfig loadDevConfig() {
        Path configPath = Path.of(readConfig("AINOVEL_CONFIG", "ainovel.config-path", "dev_config.json"));
        if (!Files.isRegularFile(configPath)) {
            return LlmConfig.empty();
        }
        try {
            Map<String, Object> root = OBJECT_MAPPER.readValue(configPath.toFile(), MAP_TYPE);
            String provider = stringValue(root.get("provider"));
            String model = stringValue(root.get("model"));
            Object providersRaw = root.get("providers");
            if (!(providersRaw instanceof Map<?, ?> providersMap)) {
                return LlmConfig.empty();
            }
            Object providerRaw = providersMap.get(provider);
            if (!(providerRaw instanceof Map<?, ?> providerMap)) {
                return LlmConfig.empty();
            }
            String apiKey = stringValue(providerMap.get("api_key"));
            String baseUrl = stringValue(providerMap.get("base_url"));
            String providerModel = stringValue(providerMap.get("model"));
            if (model.isBlank()) {
                model = providerModel;
            }
            if (baseUrl.isBlank()) {
                baseUrl = "https://api.openai.com/v1";
            }
            if (model.isBlank()) {
                return LlmConfig.empty();
            }
            return new LlmConfig(apiKey, model, baseUrl);
        } catch (IOException ex) {
            return LlmConfig.empty();
        }
    }

    private String stringValue(Object value) {
        return value == null ? "" : String.valueOf(value).trim();
    }

    private String trimTrailingSlash(String value) {
        String result = value == null ? "" : value.trim();
        while (result.endsWith("/")) {
            result = result.substring(0, result.length() - 1);
        }
        return result;
    }

    private record LlmConfig(String apiKey, String model, String baseUrl) {
        static LlmConfig empty() {
            return new LlmConfig("", "", "");
        }
    }

    private record ExtractOptions(LlmConfig config, boolean disableThinking, long timeoutMillis) {}
}
