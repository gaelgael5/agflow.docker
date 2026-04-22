-- Add parent_id to link child servers to their provisioning parent
ALTER TABLE infra_servers ADD COLUMN IF NOT EXISTS parent_id UUID REFERENCES infra_servers(id) ON DELETE SET NULL;
