-- 096_agents.sql
-- Agents SQL storage: replaces {AGFLOW_DATA_DIR}/agents/{slug}/agent.json

CREATE TABLE IF NOT EXISTS agents (
    slug                    VARCHAR(128) NOT NULL PRIMARY KEY,
    -- UUID5(slug) — deterministic, caller-supplied; never gen_random_uuid()
    id                      UUID         NOT NULL UNIQUE,
    display_name            TEXT         NOT NULL DEFAULT '',
    description             TEXT         NOT NULL DEFAULT '',
    dockerfile_id           TEXT         NOT NULL DEFAULT '',
    role_id                 TEXT         NOT NULL DEFAULT '',
    env_overrides           JSONB        NOT NULL DEFAULT '{}',
    mount_overrides         JSONB        NOT NULL DEFAULT '{}',
    param_overrides         JSONB        NOT NULL DEFAULT '{}',
    timeout_seconds         INT          NOT NULL DEFAULT 3600,
    workspace_path          TEXT         NOT NULL DEFAULT '/workspace',
    network_mode            TEXT         NOT NULL DEFAULT 'bridge',
    graceful_shutdown_secs  INT          NOT NULL DEFAULT 30,
    force_kill_delay_secs   INT          NOT NULL DEFAULT 10,
    is_assistant            BOOLEAN      NOT NULL DEFAULT FALSE,
    mcp_template_slug       TEXT         NOT NULL DEFAULT '',
    mcp_template_culture    TEXT         NOT NULL DEFAULT '',
    mcp_config_filename     TEXT         NOT NULL DEFAULT 'config.toml',
    skills_template_slug    TEXT         NOT NULL DEFAULT '',
    skills_template_culture TEXT         NOT NULL DEFAULT '',
    skills_config_filename  TEXT         NOT NULL DEFAULT 'skills.md',
    prompt_template_slug    TEXT         NOT NULL DEFAULT '',
    prompt_template_culture TEXT         NOT NULL DEFAULT '',
    prompt_filename         TEXT         NOT NULL DEFAULT 'prompt.md',
    mcp_bindings            JSONB        NOT NULL DEFAULT '[]',
    skill_bindings          JSONB        NOT NULL DEFAULT '[]',
    generations             JSONB        NOT NULL DEFAULT '[]',
    created_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TRIGGER set_updated_at_agents
    BEFORE UPDATE ON agents
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS agent_profiles (
    id               UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    agent_slug       TEXT        NOT NULL REFERENCES agents(slug) ON DELETE CASCADE,
    name             TEXT        NOT NULL,
    description      TEXT        NOT NULL DEFAULT '',
    document_ids     UUID[]      NOT NULL DEFAULT '{}',
    template_slug    TEXT        NOT NULL DEFAULT '',
    template_culture TEXT        NOT NULL DEFAULT '',
    output_dir       TEXT        NOT NULL DEFAULT 'workspace/docs/missions',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (agent_slug, name)
);

CREATE TRIGGER set_updated_at_agent_profiles
    BEFORE UPDATE ON agent_profiles
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
