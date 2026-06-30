CREATE TABLE IF NOT EXISTS story_workspace (
    story_id VARCHAR(128) PRIMARY KEY REFERENCES story_project(story_id) ON DELETE CASCADE,
    active_node_id VARCHAR(128),
    updated_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS story_workspace_node (
    node_id VARCHAR(128) PRIMARY KEY,
    story_id VARCHAR(128) NOT NULL REFERENCES story_workspace(story_id) ON DELETE CASCADE,
    parent_id VARCHAR(128),
    type VARCHAR(32) NOT NULL,
    title VARCHAR(255) NOT NULL,
    display_order INTEGER NOT NULL,
    summary TEXT,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS story_workspace_content (
    node_id VARCHAR(128) PRIMARY KEY REFERENCES story_workspace_node(node_id) ON DELETE CASCADE,
    story_id VARCHAR(128) NOT NULL REFERENCES story_workspace(story_id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS story_workspace_version (
    version_id VARCHAR(128) PRIMARY KEY,
    story_id VARCHAR(128) NOT NULL REFERENCES story_workspace(story_id) ON DELETE CASCADE,
    node_id VARCHAR(128) NOT NULL REFERENCES story_workspace_node(node_id) ON DELETE CASCADE,
    label VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    source VARCHAR(32) NOT NULL,
    created_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS story_workspace_message (
    message_id VARCHAR(128) PRIMARY KEY,
    story_id VARCHAR(128) NOT NULL REFERENCES story_workspace(story_id) ON DELETE CASCADE,
    role VARCHAR(32) NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS story_workspace_issue (
    issue_id VARCHAR(128) PRIMARY KEY,
    story_id VARCHAR(128) NOT NULL REFERENCES story_workspace(story_id) ON DELETE CASCADE,
    node_id VARCHAR(128),
    severity VARCHAR(32) NOT NULL,
    category VARCHAR(32) NOT NULL,
    title VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    status VARCHAR(32) NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS story_workspace_beat (
    beat_id VARCHAR(128) PRIMARY KEY,
    story_id VARCHAR(128) NOT NULL REFERENCES story_workspace(story_id) ON DELETE CASCADE,
    node_id VARCHAR(128) NOT NULL REFERENCES story_workspace_node(node_id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    goal TEXT NOT NULL,
    conflict TEXT NOT NULL,
    outcome TEXT NOT NULL,
    display_order INTEGER NOT NULL,
    status VARCHAR(32) NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_story_workspace_node_story_parent_order
    ON story_workspace_node(story_id, parent_id, display_order);

CREATE INDEX IF NOT EXISTS idx_story_workspace_content_story_id
    ON story_workspace_content(story_id);

CREATE INDEX IF NOT EXISTS idx_story_workspace_version_node_created_at
    ON story_workspace_version(node_id, created_at);

CREATE INDEX IF NOT EXISTS idx_story_workspace_message_story_created_at
    ON story_workspace_message(story_id, created_at);

CREATE INDEX IF NOT EXISTS idx_story_workspace_issue_story_node
    ON story_workspace_issue(story_id, node_id);

CREATE INDEX IF NOT EXISTS idx_story_workspace_beat_node_order
    ON story_workspace_beat(node_id, display_order);
