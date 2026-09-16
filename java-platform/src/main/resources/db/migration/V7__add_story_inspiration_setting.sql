-- 灵感对话：结构化设定草稿与确认态
-- 不新建表：整单确认后不存在并发写入竞争，确认只更新 session 上的两列快照。
ALTER TABLE story_inspiration_session
    ADD COLUMN IF NOT EXISTS draft_settings JSONB,
    ADD COLUMN IF NOT EXISTS draft_revision INT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS draft_source_message_id VARCHAR(128),
    ADD COLUMN IF NOT EXISTS confirmed_settings JSONB,
    ADD COLUMN IF NOT EXISTS confirmed_revision INT NOT NULL DEFAULT 0;
