-- Add name column to infra_servers
ALTER TABLE infra_servers ADD COLUMN IF NOT EXISTS name VARCHAR NOT NULL DEFAULT '';
