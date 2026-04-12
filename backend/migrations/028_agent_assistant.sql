-- 028_agent_assistant.sql
-- Marks at most one agent as the application assistant.
-- The assistant is used by the global chat button in the TopBar.
ALTER TABLE agents ADD COLUMN IF NOT EXISTS is_assistant BOOLEAN NOT NULL DEFAULT FALSE;
