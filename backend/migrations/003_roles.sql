-- 003_roles — Module 2 roles table
CREATE TABLE IF NOT EXISTS roles (
    id              TEXT PRIMARY KEY,
    display_name    TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    llm_type        TEXT NOT NULL DEFAULT 'single'
                    CHECK (llm_type IN ('single', 'multi')),
    temperature     NUMERIC(3,2) NOT NULL DEFAULT 0.3
                    CHECK (temperature >= 0 AND temperature <= 2),
    max_tokens      INTEGER NOT NULL DEFAULT 4096
                    CHECK (max_tokens > 0),
    service_types   TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    identity_md     TEXT NOT NULL DEFAULT '',
    prompt_agent_md TEXT NOT NULL DEFAULT '',
    prompt_orchestrator_md TEXT NOT NULL DEFAULT '',
    runtime_config  JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_roles_display_name ON roles(display_name);
