-- Add recipes (full registry recipes dict) to mcp_servers
-- The 'parameters' column already exists (from migration 011) but stores default values as '{}'.
-- We repurpose it to store the registry parameter definitions array.
ALTER TABLE mcp_servers ADD COLUMN IF NOT EXISTS recipes JSONB NOT NULL DEFAULT '{}';

-- Ensure parameters column holds the registry definitions (array), not old default dict
-- Only update rows that have the old default empty dict format
UPDATE mcp_servers SET parameters = '[]'::jsonb WHERE jsonb_typeof(parameters) = 'object';
