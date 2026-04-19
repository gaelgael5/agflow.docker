ALTER TABLE agent_api_contracts ADD COLUMN IF NOT EXISTS output_dir TEXT NOT NULL DEFAULT 'workspace/docs/ctr';
