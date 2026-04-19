-- 040_instance_container.sql
-- Track the currently-running container for each agent instance (for M5g /exec).

ALTER TABLE agents_instances
    ADD COLUMN IF NOT EXISTS last_container_name TEXT;

CREATE INDEX IF NOT EXISTS idx_agents_instances_last_container
    ON agents_instances (last_container_name)
    WHERE last_container_name IS NOT NULL;
