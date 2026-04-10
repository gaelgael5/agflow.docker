-- 006_drop_prompt_agent_md — redundant with identity + concatenated documents
-- The "agent prompt" (2nd person) was just a reformulation of identity + ROLES +
-- MISSIONS + COMPETENCES by Claude, which adds no value. We keep identity_md as
-- the editable 2nd person text, and we compose the final prompt at agent-launch
-- time by simple concatenation. Only the orchestrator prompt (3rd person) is
-- kept because it's a genuine 2nd→3rd person transformation.
ALTER TABLE roles DROP COLUMN IF EXISTS prompt_agent_md;
