-- M7 : Projets, Groupes, Instances — migration filesystem → PostgreSQL

-- ── Projets ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS projects (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    display_name    VARCHAR(200) NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    environment     VARCHAR(20) NOT NULL DEFAULT 'dev'
                    CHECK (environment IN ('dev', 'staging', 'prod')),
    tags            JSONB NOT NULL DEFAULT '[]',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TRIGGER trg_projects_updated_at
    BEFORE UPDATE ON projects FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ── Groupes logiques ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS groups (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name            VARCHAR(200) NOT NULL,
    max_agents      INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(project_id, name)
);

CREATE TRIGGER trg_groups_updated_at
    BEFORE UPDATE ON groups FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ── Instances logiques ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS instances (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_id        UUID NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    instance_name   VARCHAR(128) NOT NULL,
    catalog_id      VARCHAR(128) NOT NULL,
    variables       JSONB NOT NULL DEFAULT '{}',
    status          VARCHAR(20) NOT NULL DEFAULT 'draft'
                    CHECK (status IN ('draft', 'active', 'stopped')),
    service_url     VARCHAR,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(group_id, instance_name)
);

CREATE TRIGGER trg_instances_updated_at
    BEFORE UPDATE ON instances FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX IF NOT EXISTS idx_groups_project_id ON groups(project_id);
CREATE INDEX IF NOT EXISTS idx_instances_group_id ON instances(group_id);
