-- 013_agents — Module 4 composed agents (Dockerfile + Role + lifecycle)
CREATE TABLE IF NOT EXISTS agents (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    slug                    TEXT UNIQUE NOT NULL,
    display_name            TEXT NOT NULL,
    description             TEXT NOT NULL DEFAULT '',
    dockerfile_id           TEXT NOT NULL REFERENCES dockerfiles(id) ON DELETE RESTRICT,
    role_id                 TEXT NOT NULL REFERENCES roles(id)       ON DELETE RESTRICT,
    env_vars                JSONB NOT NULL DEFAULT '{}'::jsonb,
    timeout_seconds         INTEGER NOT NULL DEFAULT 3600 CHECK (timeout_seconds > 0),
    workspace_path          TEXT   NOT NULL DEFAULT '/workspace',
    network_mode            TEXT   NOT NULL DEFAULT 'bridge'
                            CHECK (network_mode IN ('bridge', 'host', 'none')),
    graceful_shutdown_secs  INTEGER NOT NULL DEFAULT 30 CHECK (graceful_shutdown_secs >= 0),
    force_kill_delay_secs   INTEGER NOT NULL DEFAULT 10 CHECK (force_kill_delay_secs >= 0),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agents_slug       ON agents(slug);
CREATE INDEX IF NOT EXISTS idx_agents_dockerfile ON agents(dockerfile_id);
CREATE INDEX IF NOT EXISTS idx_agents_role       ON agents(role_id);
