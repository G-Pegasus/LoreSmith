CREATE TABLE IF NOT EXISTS story_workspace_reference (
    story_id VARCHAR(128) PRIMARY KEY REFERENCES story_workspace(story_id) ON DELETE CASCADE,
    premise_md TEXT NOT NULL DEFAULT '',
    outline_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    characters_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    world_rules_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    timeline_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    relationship_state_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    foreshadow_ledger_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    source VARCHAR(32) NOT NULL DEFAULT 'legacy_file_backfill',
    updated_at TIMESTAMP NOT NULL,
    CONSTRAINT chk_story_workspace_reference_outline_array CHECK (jsonb_typeof(outline_json) = 'array'),
    CONSTRAINT chk_story_workspace_reference_characters_array CHECK (jsonb_typeof(characters_json) = 'array'),
    CONSTRAINT chk_story_workspace_reference_world_rules_array CHECK (jsonb_typeof(world_rules_json) = 'array'),
    CONSTRAINT chk_story_workspace_reference_timeline_array CHECK (jsonb_typeof(timeline_json) = 'array'),
    CONSTRAINT chk_story_workspace_reference_relationship_array CHECK (jsonb_typeof(relationship_state_json) = 'array'),
    CONSTRAINT chk_story_workspace_reference_foreshadow_array CHECK (jsonb_typeof(foreshadow_ledger_json) = 'array')
);
