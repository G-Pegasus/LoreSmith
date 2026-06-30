ALTER TABLE story_workspace
    ADD COLUMN active_run_id VARCHAR(128),
    ADD COLUMN run_after_seq INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN run_sync_status VARCHAR(32) NOT NULL DEFAULT 'idle',
    ADD COLUMN run_sync_updated_at TIMESTAMP;