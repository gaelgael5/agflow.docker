-- 035_agents_to_disk.sql
-- Agent data migrated to filesystem at {AGFLOW_DATA_DIR}/agents/{slug}/agent.json.
-- DB keeps only existence tracking.
DROP TABLE IF EXISTS agent_profiles;
DROP TABLE IF EXISTS agent_skills;
DROP TABLE IF EXISTS agent_mcp_servers;

-- Strip agents table to minimal columns
ALTER TABLE agents DROP COLUMN IF EXISTS display_name;
ALTER TABLE agents DROP COLUMN IF EXISTS description;
ALTER TABLE agents DROP COLUMN IF EXISTS dockerfile_id;
ALTER TABLE agents DROP COLUMN IF EXISTS role_id;
ALTER TABLE agents DROP COLUMN IF EXISTS env_vars;
ALTER TABLE agents DROP COLUMN IF EXISTS timeout_seconds;
ALTER TABLE agents DROP COLUMN IF EXISTS workspace_path;
ALTER TABLE agents DROP COLUMN IF EXISTS network_mode;
ALTER TABLE agents DROP COLUMN IF EXISTS graceful_shutdown_secs;
ALTER TABLE agents DROP COLUMN IF EXISTS force_kill_delay_secs;
ALTER TABLE agents DROP COLUMN IF EXISTS is_assistant;
