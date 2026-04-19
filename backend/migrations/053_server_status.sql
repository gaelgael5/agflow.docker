-- Add status column to infra_servers
ALTER TABLE infra_servers ADD COLUMN IF NOT EXISTS status VARCHAR NOT NULL DEFAULT 'not_initialized';
