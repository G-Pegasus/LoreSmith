CREATE TABLE IF NOT EXISTS story_workspace_reference (
    story_id VARCHAR(128) PRIMARY KEY,
    premise_md TEXT NOT NULL DEFAULT '',
    outline_json JSON NOT NULL DEFAULT (JSON_ARRAY()),
    characters_json JSON NOT NULL DEFAULT (JSON_ARRAY()),
    world_rules_json JSON NOT NULL DEFAULT (JSON_ARRAY()),
    timeline_json JSON NOT NULL DEFAULT (JSON_ARRAY()),
    relationship_json JSON NOT NULL DEFAULT (JSON_ARRAY()),
    foreshadow_ledger_json JSON NOT NULL DEFAULT (JSON_ARRAY()),
    source VARCHAR(32) NOT NULL DEFAULT 'manual_backfill',
    updated_at TIMESTAMP NOT NULL,
    FOREIGN KEY (story_id) REFERENCES story_workspace(story_id) ON DELETE CASCADE,
    CONSTRAINT chk_story_workspace_reference_outline CHECK (JSON_VALID(outline_json)),
    CONSTRAINT chk_story_workspace_reference_characters CHECK (JSON_VALID(characters_json)),
    CONSTRAINT chk_story_workspace_reference_world_rules CHECK (JSON_VALID(world_rules_json)),
    CONSTRAINT chk_story_workspace_reference_timeline CHECK (JSON_VALID(timeline_json)),
    CONSTRAINT chk_story_workspace_reference_relationship CHECK (JSON_VALID(relationship_json)),
    CONSTRAINT chk_story_workspace_reference_foreshadow CHECK (JSON_VALID(foreshadow_ledger_json))
);