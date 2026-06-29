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
    StoryInspirationMessageRecord saveMessage(StoryInspirationMessageRecord message);
    List<StoryInspirationMessageRecord> listMessages(String sessionId);
}
