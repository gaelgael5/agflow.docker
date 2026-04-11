-- 017_agent_profiles — mission profiles for agents
--
-- A profile is a named bundle of document references (picked cross-category
-- from the agent's role) that is optionally applied at agent instantiation.
-- Without a profile, only the role identity is injected into the prompt;
-- with a profile, the referenced documents are appended on top.
--
-- Design decision: document_ids is stored as a UUID[] (not a link table)
-- deliberately, so that deleting a role_document or changing the agent's
-- role leaves the profile intact with dangling UUIDs — the composition
-- builder then detects these as broken refs and flags the agent as
-- "in error" rather than silently dropping the reference.

CREATE TABLE IF NOT EXISTS agent_profiles (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id        UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    document_ids    UUID[] NOT NULL DEFAULT '{}'::uuid[],
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (agent_id, name)
);

CREATE INDEX IF NOT EXISTS idx_agent_profiles_agent ON agent_profiles(agent_id);
