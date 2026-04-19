-- Add runtime_base_url column to agent_api_contracts
-- Used in generated .sh scripts instead of base_url (public reference).
-- Defaults to empty string (meaning: use base_url as fallback).
ALTER TABLE agent_api_contracts
    ADD COLUMN IF NOT EXISTS runtime_base_url TEXT NOT NULL DEFAULT '';
