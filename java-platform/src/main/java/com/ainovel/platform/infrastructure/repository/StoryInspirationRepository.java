package com.ainovel.platform.infrastructure.repository;

import com.ainovel.platform.domain.model.StoryInspirationMessageRecord;
import com.ainovel.platform.domain.model.StoryInspirationSessionRecord;

import java.time.Instant;
import java.util.List;
import java.util.Optional;

public interface StoryInspirationRepository {
    Optional<StoryInspirationSessionRecord> findSession(String sessionId);

    StoryInspirationSessionRecord upsertSession(String sessionId, String memorySummary, Instant now);

    StoryInspirationSessionRecord updateMemory(String sessionId, String memorySummary, Instant updatedAt);

    /**
     * 覆写当前设定草稿与待确认卡指针。
     *
     * @param draftSettings       草稿 JSON；null 表示"还没有草稿"
     * @param draftRevision       当前草稿版本号
     * @param draftSourceMessageId 待确认卡挂载的 assistant 消息 id；没有待确认卡时传 null
     */
    StoryInspirationSessionRecord updateDraft(
            String sessionId,
            String draftSettings,
            int draftRevision,
            String draftSourceMessageId,
            Instant updatedAt
    );

    /** 记录用户确认结果，并清空待确认卡指针（确认单不再需要在流内渲染）。 */
    StoryInspirationSessionRecord updateConfirmed(
            String sessionId,
            String confirmedSettings,
            int confirmedRevision,
            Instant updatedAt
    );

    StoryInspirationMessageRecord saveMessage(StoryInspirationMessageRecord message);

    List<StoryInspirationMessageRecord> listMessages(String sessionId);

    /**
     * 删除整个会话。消息表的外键带 ON DELETE CASCADE，所以这一条 DELETE 会连带清空全部消息，
     * 不需要再单独删消息表。
     *
     * @return 是否真的删掉了一行（删不存在的会话返回 false，不抛异常 —— 重置操作要幂等）
     */
    boolean deleteSession(String sessionId);
}
