-- 039_sessions_and_agents.sql
-- M5c + M5d: sessions + agent instances + minimal agents registry

CREATE TABLE IF NOT EXISTS agents_catalog (
    slug        TEXT PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sessions (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    api_key_id   UUID NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE,
    name         TEXT,
    status       TEXT NOT NULL DEFAULT 'active'
                 CHECK (status IN ('active','closed','expired')),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at   TIMESTAMPTZ NOT NULL,
    closed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_sessions_api_key ON sessions (api_key_id, status);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions (expires_at) WHERE status = 'active';

CREATE TABLE IF NOT EXISTS agents_instances (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id    UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    agent_id      TEXT NOT NULL REFERENCES agents_catalog(slug) ON DELETE RESTRICT,
    labels        JSONB NOT NULL DEFAULT '{}',
    mission       TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    destroyed_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_agents_instances_session
    ON agents_instances (session_id) WHERE destroyed_at IS NULL;
