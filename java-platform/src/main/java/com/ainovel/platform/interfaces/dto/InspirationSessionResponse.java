package com.ainovel.platform.interfaces.dto;

import java.util.List;

/**
 * 灵感对话会话的完整状态快照。{@code done} 事件与 GET / confirm 都返回这个形状，
 * 前端只做渲染、不做任何增量合并。
 *
 * @param draft                当前设定草稿；尚未抽出任何内容时为 null
 * @param draftRevision        当前草稿版本号，有实质变化才 +1
 * @param confirmedRevision    用户最后一次确认时的草稿版本号；{@code draftRevision > confirmedRevision} 即"有未确认更新"
 * @param draftSourceMessageId 待确认卡挂载的 assistant 消息 id；没有待确认卡时为 null
 * @param confirmedSettings    用户最后一次确认的快照，供前端标记「新增 / 已修改」
 */
public record InspirationSessionResponse(
        String sessionId,
        String memorySummary,
        List<InspirationMessageResponse> messages,
        String updatedAt,
        InspirationSettingsResponse draft,
        int draftRevision,
        int confirmedRevision,
        String draftSourceMessageId,
        InspirationSettingsResponse confirmedSettings
) {}
