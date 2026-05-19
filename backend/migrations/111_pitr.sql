-- 111_pitr.sql — PITR (Point-In-Time Recovery via pgBackRest)

CREATE TABLE pitr_basebackups (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    pgbackrest_label        text NOT NULL UNIQUE,
    started_at              timestamptz NOT NULL,
    completed_at            timestamptz,
    size_bytes              bigint,
    status                  text NOT NULL CHECK (status IN ('running', 'ok', 'failed')),
    error                   text,
    recovery_window_start   timestamptz,
    recovery_window_end     timestamptz,
    created_at              timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_pitr_basebackups_started_at ON pitr_basebackups (started_at DESC);
CREATE INDEX idx_pitr_basebackups_status ON pitr_basebackups (status) WHERE status = 'running';

CREATE TABLE pitr_basebackup_pushes (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    basebackup_id           uuid NOT NULL REFERENCES pitr_basebackups(id) ON DELETE CASCADE,
    remote_connection_id    uuid NOT NULL REFERENCES remote_backup_connections(id) ON DELETE CASCADE,
    status                  text NOT NULL CHECK (status IN ('pending', 'pushing', 'ok', 'failed')),
    pushed_at               timestamptz,
    error                   text,
    remote_path             text,
    size_bytes              bigint,
    created_at              timestamptz NOT NULL DEFAULT now(),
    updated_at              timestamptz NOT NULL DEFAULT now(),
    UNIQUE (basebackup_id, remote_connection_id)
);

CREATE INDEX idx_pitr_pushes_basebackup ON pitr_basebackup_pushes (basebackup_id);
CREATE INDEX idx_pitr_pushes_remote ON pitr_basebackup_pushes (remote_connection_id);

CREATE TABLE pitr_config (
    id                      int PRIMARY KEY CHECK (id = 1),
    enabled                 boolean NOT NULL DEFAULT true,
    basebackup_cron         text NOT NULL DEFAULT '0 3 * * *',
    retention_count         int NOT NULL DEFAULT 7 CHECK (retention_count >= 1),
    updated_at              timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE pitr_config_remotes (
    config_id               int NOT NULL REFERENCES pitr_config(id) ON DELETE CASCADE,
    remote_connection_id    uuid NOT NULL REFERENCES remote_backup_connections(id) ON DELETE CASCADE,
    PRIMARY KEY (config_id, remote_connection_id)
);

CREATE TABLE pitr_clones (
    id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    basebackup_id           uuid NOT NULL REFERENCES pitr_basebackups(id) ON DELETE RESTRICT,
    target_time             timestamptz NOT NULL,
    status                  text NOT NULL CHECK (status IN ('restoring', 'ready', 'terminating', 'terminated', 'failed')),
    error                   text,
    postgres_container_id   text,
    postgres_container_name text,
    pgweb_container_id      text,
    pgweb_container_name    text,
    pgweb_port              int,
    started_at              timestamptz NOT NULL DEFAULT now(),
    ready_at                timestamptz,
    expires_at              timestamptz NOT NULL,
    terminated_at           timestamptz,
    created_by_user_id      uuid REFERENCES users(id) ON DELETE SET NULL
);

CREATE UNIQUE INDEX idx_pitr_clones_one_active
    ON pitr_clones (id)
    WHERE status IN ('restoring', 'ready', 'terminating');

CREATE INDEX idx_pitr_clones_status ON pitr_clones (status);
CREATE INDEX idx_pitr_clones_expires_at ON pitr_clones (expires_at) WHERE status IN ('restoring', 'ready');

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_pitr_pushes_updated_at') THEN
        CREATE TRIGGER trg_pitr_pushes_updated_at
            BEFORE UPDATE ON pitr_basebackup_pushes
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_pitr_config_updated_at') THEN
        CREATE TRIGGER trg_pitr_config_updated_at
            BEFORE UPDATE ON pitr_config
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
END $$;

INSERT INTO pitr_config (id, enabled, basebackup_cron, retention_count)
VALUES (1, true, '0 3 * * *', 7)
ON CONFLICT (id) DO NOTHING;
