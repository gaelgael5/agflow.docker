-- Matérialisation du déploiement d'un projet.
--
-- project_runtimes         = un runtime complet (un push d'un deployment) ;
--                            porte l'utilisateur, le deployment, le status global
-- project_group_runtimes   = détail par groupe × machine au sein du runtime ;
--                            porte env + compose + remote_path, UUID servant
--                            de label docker pour filtrer les conteneurs

CREATE TABLE IF NOT EXISTS project_runtimes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    deployment_id   UUID REFERENCES project_deployments(id) ON DELETE SET NULL,
    user_id         UUID REFERENCES users(id) ON DELETE SET NULL,
    status          VARCHAR NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'deployed', 'failed')),
    pushed_at       TIMESTAMPTZ,
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_project_runtimes_project ON project_runtimes(project_id);
CREATE INDEX IF NOT EXISTS idx_project_runtimes_deployment
    ON project_runtimes(deployment_id) WHERE deployment_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS project_group_runtimes (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_runtime_id  UUID NOT NULL REFERENCES project_runtimes(id) ON DELETE CASCADE,
    group_id            UUID NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    machine_id          UUID REFERENCES infra_machines(id) ON DELETE SET NULL,
    env_text            TEXT NOT NULL DEFAULT '',
    compose_yaml        TEXT NOT NULL DEFAULT '',
    remote_path         TEXT NOT NULL DEFAULT '',
    status              VARCHAR NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'deployed', 'failed')),
    pushed_at           TIMESTAMPTZ,
    error_message       TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (project_runtime_id, group_id)
);

CREATE INDEX IF NOT EXISTS idx_project_group_runtimes_runtime
    ON project_group_runtimes(project_runtime_id);
CREATE INDEX IF NOT EXISTS idx_project_group_runtimes_group
    ON project_group_runtimes(group_id);
CREATE INDEX IF NOT EXISTS idx_project_group_runtimes_machine
    ON project_group_runtimes(machine_id) WHERE machine_id IS NOT NULL;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_project_runtimes_updated_at') THEN
        CREATE TRIGGER trg_project_runtimes_updated_at
            BEFORE UPDATE ON project_runtimes
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_project_group_runtimes_updated_at') THEN
        CREATE TRIGGER trg_project_group_runtimes_updated_at
            BEFORE UPDATE ON project_group_runtimes
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
END $$;
