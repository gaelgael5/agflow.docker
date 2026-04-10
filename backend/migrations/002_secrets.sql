-- 002_secrets — Module 0 secrets table
CREATE TABLE IF NOT EXISTS secrets (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    var_name        TEXT NOT NULL,
    value_encrypted BYTEA NOT NULL,
    scope           TEXT NOT NULL DEFAULT 'global'
                    CHECK (scope IN ('global', 'agent')),
    agent_id        UUID NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (var_name, scope, agent_id)
);

CREATE INDEX IF NOT EXISTS idx_secrets_var_name ON secrets(var_name);
