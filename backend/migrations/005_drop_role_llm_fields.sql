-- 005_drop_role_llm_fields — remove llm_type, temperature, max_tokens from roles
-- Per-role LLM configuration moves out of the role entity. The prompt generator
-- uses a constant default instead.
ALTER TABLE roles DROP COLUMN IF EXISTS llm_type;
ALTER TABLE roles DROP COLUMN IF EXISTS temperature;
ALTER TABLE roles DROP COLUMN IF EXISTS max_tokens;
