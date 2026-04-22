-- Project deployments — concrete instances of projects on servers
CREATE TABLE IF NOT EXISTS project_deployments (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id          UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id             UUID NOT NULL REFERENCES users(id),
    group_servers       JSONB NOT NULL DEFAULT '{}',
    status              VARCHAR(20) NOT NULL DEFAULT 'draft'
                        CHECK (status IN ('draft', 'generated', 'deployed')),
    generated_compose   TEXT,
    generated_env       TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TRIGGER trg_project_deployments_updated_at
    BEFORE UPDATE ON project_deployments FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE INDEX IF NOT EXISTS idx_project_deployments_project_id ON project_deployments(project_id);
CREATE INDEX IF NOT EXISTS idx_project_deployments_user_id ON project_deployments(user_id);
