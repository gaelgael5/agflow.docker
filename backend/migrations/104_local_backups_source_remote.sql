-- 104 — Trace la connexion remote d'origine d'un backup local pull

ALTER TABLE local_backups
    ADD COLUMN source_remote_connection_id UUID
        REFERENCES remote_backup_connections(id) ON DELETE SET NULL;

CREATE INDEX idx_local_backups_source_remote
    ON local_backups(source_remote_connection_id)
    WHERE source_remote_connection_id IS NOT NULL;
