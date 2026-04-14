-- 036_drop_agents_table.sql
-- Agents fully on disk at {AGFLOW_DATA_DIR}/agents/{slug}/agent.json.
-- UUID computed deterministically from slug. No DB needed.
DROP TABLE IF EXISTS agents CASCADE;
