ALTER TABLE agent_api_contracts ADD COLUMN IF NOT EXISTS tag_overrides JSONB NOT NULL DEFAULT '{}';
ALTER TABLE agent_api_contracts ADD COLUMN IF NOT EXISTS managed_by_instance UUID;
