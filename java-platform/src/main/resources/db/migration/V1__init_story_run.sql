CREATE TABLE IF NOT EXISTS story_project (
    story_id VARCHAR(128) PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    premise TEXT NOT NULL,
    style_code VARCHAR(64) NOT NULL,
    latest_run_id VARCHAR(128) NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS story_run (
    run_id VARCHAR(128) PRIMARY KEY,
    story_id VARCHAR(128) NOT NULL,
    status VARCHAR(64) NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE INDEX idx_story_run_story_id ON story_run(story_id);