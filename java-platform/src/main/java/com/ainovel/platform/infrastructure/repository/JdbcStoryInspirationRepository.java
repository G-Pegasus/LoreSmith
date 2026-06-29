package com.ainovel.platform.infrastructure.repository;

import com.ainovel.platform.domain.model.StoryInspirationMessageRecord;
import com.ainovel.platform.domain.model.StoryInspirationSessionRecord;
import jakarta.annotation.PostConstruct;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Optional;

@Repository
public class JdbcStoryInspirationRepository implements StoryInspirationRepository {
    private final JdbcTemplate jdbcTemplate;

    public JdbcStoryInspirationRepository(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    @PostConstruct
    void ensureSchema() {
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS story_inspiration_session (
                    session_id VARCHAR(128) PRIMARY KEY,
                    memory_summary TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL
                )
                """);
        jdbcTemplate.execute("""
                CREATE TABLE IF NOT EXISTS story_inspiration_message (
                    message_id VARCHAR(128) PRIMARY KEY,
                    session_id VARCHAR(128) NOT NULL REFERENCES story_inspiration_session(session_id) ON DELETE CASCADE,
                    role VARCHAR(32) NOT NULL,
                    content TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL
                )
                """);
        jdbcTemplate.execute("""
                CREATE INDEX IF NOT EXISTS idx_story_inspiration_message_session_created_at
                    ON story_inspiration_message(session_id, created_at)
                """);
    }

    @Override
    public Optional<StoryInspirationSessionRecord> findSession(String sessionId) {
        List<StoryInspirationSessionRecord> rows = jdbcTemplate.query("""
                SELECT session_id, memory_summary, created_at, updated_at
                FROM story_inspiration_session
                WHERE session_id = ?
                """, this::mapSession, sessionId);
        return rows.stream().findFirst();
    }

    @Override
    public StoryInspirationSessionRecord upsertSession(String sessionId, String memorySummary, Instant now) {
        jdbcTemplate.update("""
                INSERT INTO story_inspiration_session (session_id, memory_summary, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (session_id) DO UPDATE SET
                    updated_at = EXCLUDED.updated_at
                """,
                sessionId,
                memorySummary == null ? "" : memorySummary,
                Timestamp.from(now),
                Timestamp.from(now)
        );
        return findSession(sessionId).orElseThrow(() -> new IllegalStateException("failed to load inspiration session"));
    }

    @Override
    public StoryInspirationSessionRecord updateMemory(String sessionId, String memorySummary, Instant updatedAt) {
        jdbcTemplate.update("""
                UPDATE story_inspiration_session
                SET memory_summary = ?, updated_at = ?
                WHERE session_id = ?
                """,
                memorySummary == null ? "" : memorySummary,
                Timestamp.from(updatedAt),
                sessionId
        );
        return findSession(sessionId).orElseThrow(() -> new IllegalArgumentException("inspiration session not found: " + sessionId));
    }

    @Override
    public StoryInspirationMessageRecord saveMessage(StoryInspirationMessageRecord message) {
        jdbcTemplate.update("""
                INSERT INTO story_inspiration_message (message_id, session_id, role, content, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                message.messageId(),
                message.sessionId(),
                message.role(),
                message.content(),
                Timestamp.from(message.createdAt())
        );
        jdbcTemplate.update("UPDATE story_inspiration_session SET updated_at = ? WHERE session_id = ?",
                Timestamp.from(message.createdAt()),
                message.sessionId()
        );
        return message;
    }

    @Override
    public List<StoryInspirationMessageRecord> listMessages(String sessionId) {
        return jdbcTemplate.query("""
                SELECT message_id, session_id, role, content, created_at
                FROM story_inspiration_message
                WHERE session_id = ?
                ORDER BY created_at ASC
                """, this::mapMessage, sessionId);
    }

    private StoryInspirationSessionRecord mapSession(ResultSet rs, int rowNum) throws SQLException {
        return new StoryInspirationSessionRecord(
                rs.getString("session_id"),
                rs.getString("memory_summary"),
                rs.getTimestamp("created_at").toInstant(),
                rs.getTimestamp("updated_at").toInstant()
        );
    }

    private StoryInspirationMessageRecord mapMessage(ResultSet rs, int rowNum) throws SQLException {
        return new StoryInspirationMessageRecord(
                rs.getString("message_id"),
                rs.getString("session_id"),
                rs.getString("role"),
                rs.getString("content"),
                rs.getTimestamp("created_at").toInstant()
        );
    }
}
