-- Suppression logique des runtimes.
-- deleted_at non-null = runtime supprimé (n'apparaît plus dans la liste UI).
-- La suppression physique (docker compose down + rm -rf) se fait côté endpoint
-- avant de marquer la ligne en BDD.
ALTER TABLE project_runtimes
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

ALTER TABLE project_group_runtimes
    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_project_runtimes_not_deleted
    ON project_runtimes(project_id, seq DESC) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_project_group_runtimes_not_deleted
    ON project_group_runtimes(group_id, seq DESC) WHERE deleted_at IS NULL;
