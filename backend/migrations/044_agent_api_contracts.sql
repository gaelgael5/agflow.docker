CREATE TABLE IF NOT EXISTS agent_api_contracts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id        TEXT NOT NULL,
    slug            TEXT NOT NULL,
    display_name    TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    source_type     TEXT NOT NULL DEFAULT 'manual'
                    CHECK (source_type IN ('upload', 'url', 'manual')),
    source_url      TEXT,
    spec_content    TEXT NOT NULL,
    base_url        TEXT NOT NULL DEFAULT '',
    auth_header     TEXT NOT NULL DEFAULT 'Authorization',
    auth_prefix     TEXT NOT NULL DEFAULT 'Bearer',
    auth_secret_ref TEXT,
    parsed_tags     JSONB NOT NULL DEFAULT '[]',
    position        INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (agent_id, slug)
);

CREATE INDEX IF NOT EXISTS idx_agent_api_contracts_agent
    ON agent_api_contracts(agent_id, position);
