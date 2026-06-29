package com.ainovel.platform.application;

import com.ainovel.platform.domain.model.StoryInspirationMessageRecord;
import com.fasterxml.jackson.core.type.TypeReference;
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
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Consumer;

@Component
public class InspirationAiClient {
    private static final Logger LOGGER = LoggerFactory.getLogger(InspirationAiClient.class);
    private static final ObjectMapper OBJECT_MAPPER = new ObjectMapper();
    private static final TypeReference<Map<String, Object>> MAP_TYPE = new TypeReference<>() {};

    public static final String SYSTEM_PROMPT = """
            你是“墨韵AI”的专业小说创作灵感顾问，只负责帮助用户完成作品构思，不直接替用户创建作品，也不输出冗长正文。

            角色定位：
            - 你是资深网文策划、故事编辑和世界观架构师。
            - 你擅长从用户零散设定中识别题材、叙事风格、核心矛盾、人物欲望和可持续连载的故事引擎。
            - 你必须主动保护用户原创性：不要套模板替换名词，不要泛泛而谈，不要用空洞宣传语。

            输出逻辑：
            1. 先用 2-3 句复述你理解到的创作目标，指出最有潜力的故事钩子。
            2. 再给“设定拓展”：补充世界规则、冲突来源、人物关系、隐藏代价或反转可能。
            3. 再给“大纲建议”：优先输出黄金三章或 5-8 个阶段性剧情节点，说明每段的读者期待。
            4. 再给“可直接填入新建作品页的精炼设定”：用一段 150-300 字中文总结。
            5. 最后提出 2-3 个高价值追问，引导用户继续澄清。

            记忆规则：
            - 你会收到“长期记忆摘要”和最近多轮对话。必须延续用户已确认的设定，不得遗忘或自相矛盾。
            - 当用户修改设定时，以最新说法为准，并指出哪些旧建议需要同步调整。
            - 如果信息不足，先给可选方向，不要强行定死。

            风格要求：
            - 中文输出，结构清晰，标题短，建议具体。
            - 避免“命运齿轮开始转动”“前所未有的挑战”等 AI 腔套话。
            - 不输出安全无关免责声明。
            """;

    private final WebClient webClient;
    private final Environment environment;

    public InspirationAiClient(WebClient.Builder builder, Environment environment) {
        this.webClient = builder.build();
        this.environment = environment;
    }

    public String stream(String memorySummary, List<StoryInspirationMessageRecord> recentMessages, Consumer<String> deltaConsumer) {
        LlmConfig config = loadDevConfig();
        if (config.apiKey().isBlank()) {
            return emitFallback(memorySummary, recentMessages, deltaConsumer);
        }

        StringBuilder assistantContent = new StringBuilder();
        StringBuilder lineBuffer = new StringBuilder();
        try {
            Map<String, Object> payload = new LinkedHashMap<>();
            payload.put("model", config.model());
            payload.put("temperature", 0.78);
            payload.put("stream", true);
            payload.put("messages", buildMessages(memorySummary, recentMessages));

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

    private List<Map<String, String>> buildMessages(String memorySummary, List<StoryInspirationMessageRecord> recentMessages) {
        List<Map<String, String>> messages = new ArrayList<>();
        messages.add(Map.of("role", "system", "content", SYSTEM_PROMPT));
        if (memorySummary != null && !memorySummary.isBlank()) {
            messages.add(Map.of("role", "system", "content", "长期记忆摘要：\n" + memorySummary));
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

                ## 大纲建议
                1. 第一章用一个不可逆事件开场，让主角必须行动。
                2. 第二章展示世界规则的代价，并引出第一个关键人物。
                3. 第三章让主角做出错误但合理的选择，制造持续追读的悬念。
                4. 中段安排一次认知反转：主角以为自己在解决问题，其实在靠近更大的真相。
                5. 阶段结尾回收一个早期细节，同时打开更大的矛盾。

                ## 可直接填入新建作品页的精炼设定
                这是一部以强冲突和持续反转驱动的长篇故事。主角在一个规则严苛、代价明确的世界中被迫追求某个不可替代的目标。每一次推进都会带来新的关系变化和隐藏风险，人物选择既解决眼前危机，也不断暴露更深层的秘密。

                ## 继续追问
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

    @SuppressWarnings("unchecked")
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
}
