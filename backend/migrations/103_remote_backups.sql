-- 103 — remote_backup_connections, local_backups, system_anomaly_events

-- ─── remote_backup_connections ─────────────────────────────────────────────

CREATE TABLE remote_backup_connections (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name                TEXT        NOT NULL,
    kind                TEXT        NOT NULL CHECK (kind IN ('sftp', 's3', 'ftps')),
    config              JSONB       NOT NULL DEFAULT '{}',
    vault_api_key_id    TEXT,
    vault_secret_path   TEXT,
    CONSTRAINT rbc_vault_both_or_none CHECK (
        (vault_api_key_id IS NULL) = (vault_secret_path IS NULL)
    ),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by_user_id  UUID        REFERENCES users(id) ON DELETE SET NULL,
    deleted_at          TIMESTAMPTZ
);

CREATE UNIQUE INDEX idx_rbc_name_active
    ON remote_backup_connections(lower(name))
    WHERE deleted_at IS NULL;

CREATE INDEX idx_rbc_deleted ON remote_backup_connections(deleted_at);

CREATE TRIGGER trg_rbc_updated_at
    BEFORE UPDATE ON remote_backup_connections
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ─── local_backups ─────────────────────────────────────────────────────────

CREATE TABLE local_backups (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    filename            TEXT        NOT NULL,
    file_path           TEXT        NOT NULL,
    size_bytes          BIGINT,
    status              TEXT        NOT NULL DEFAULT 'completed'
                        CHECK (status IN ('in_progress', 'completed', 'failed')),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by_user_id  UUID        REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX idx_local_backups_created ON local_backups(created_at DESC);

-- ─── system_anomaly_events ─────────────────────────────────────────────────

CREATE TABLE system_anomaly_events (
    id                          BIGSERIAL   PRIMARY KEY,
    detected_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    severity                    TEXT        NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
    anomaly_type                TEXT        NOT NULL,
    source                      TEXT        NOT NULL,
    source_ref_id               UUID,
    message                     TEXT        NOT NULL,
    metadata                    JSONB       NOT NULL DEFAULT '{}',
    acknowledged_at             TIMESTAMPTZ,
    acknowledged_by_user_id     UUID        REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX idx_sae_pending
    ON system_anomaly_events(detected_at DESC)
    WHERE acknowledged_at IS NULL;

CREATE INDEX idx_sae_source ON system_anomaly_events(source, source_ref_id);
