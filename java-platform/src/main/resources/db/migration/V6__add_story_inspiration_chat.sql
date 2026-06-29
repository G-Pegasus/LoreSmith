CREATE TABLE IF NOT EXISTS story_inspiration_session (
    session_id VARCHAR(128) PRIMARY KEY,
    memory_summary TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS story_inspiration_message (
    message_id VARCHAR(128) PRIMARY KEY,
    session_id VARCHAR(128) NOT NULL REFERENCES story_inspiration_session(session_id) ON DELETE CASCADE,
    role VARCHAR(32) NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_story_inspiration_message_session_created_at
    ON story_inspiration_message(session_id, created_at);
