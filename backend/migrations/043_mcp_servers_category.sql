-- Add category column to mcp_servers (stored from registry at install time)
ALTER TABLE mcp_servers ADD COLUMN IF NOT EXISTS category TEXT NOT NULL DEFAULT '';
