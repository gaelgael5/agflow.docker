-- Add project_id column to sessions
-- Links a session to a project so agents inherit the project's MCP and API contracts
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS project_id TEXT;
