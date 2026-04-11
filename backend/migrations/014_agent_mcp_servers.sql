-- 014_agent_mcp_servers — N-N binding between agents and MCP catalog
CREATE TABLE IF NOT EXISTS agent_mcp_servers (
    agent_id             UUID NOT NULL REFERENCES agents(id)      ON DELETE CASCADE,
    mcp_server_id        UUID NOT NULL REFERENCES mcp_servers(id) ON DELETE RESTRICT,
    parameters_override  JSONB NOT NULL DEFAULT '{}'::jsonb,
    position             INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (agent_id, mcp_server_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_mcp_agent ON agent_mcp_servers(agent_id, position);
