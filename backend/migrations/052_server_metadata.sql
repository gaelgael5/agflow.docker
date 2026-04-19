-- Add metadata JSONB column to infra_servers for provisioning info
ALTER TABLE infra_servers ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}';
