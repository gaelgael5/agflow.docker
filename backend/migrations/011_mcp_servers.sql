-- 011_mcp_servers — Module 3b local catalog of MCP servers installed from registries
CREATE TABLE IF NOT EXISTS mcp_servers (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    discovery_service_id TEXT NOT NULL REFERENCES discovery_services(id) ON DELETE CASCADE,
    package_id        TEXT NOT NULL,
    name              TEXT NOT NULL,
    repo              TEXT NOT NULL DEFAULT '',
    repo_url          TEXT NOT NULL DEFAULT '',
    transport         TEXT NOT NULL DEFAULT 'stdio'
                      CHECK (transport IN ('stdio', 'sse', 'docker')),
    short_description TEXT NOT NULL DEFAULT '',
    long_description  TEXT NOT NULL DEFAULT '',
    documentation_url TEXT NOT NULL DEFAULT '',
    parameters        JSONB NOT NULL DEFAULT '{}'::jsonb,
    parameters_schema JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (discovery_service_id, package_id)
);

CREATE INDEX IF NOT EXISTS idx_mcp_servers_repo ON mcp_servers(repo);
