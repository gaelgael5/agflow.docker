-- 114_backup_schedules_multi_remote.sql
-- Multi-remote pour backup_schedules_full + push history par remote

CREATE TABLE backup_schedule_full_remotes (
    schedule_id          uuid NOT NULL REFERENCES backup_schedules_full(id) ON DELETE CASCADE,
    remote_connection_id uuid NOT NULL REFERENCES remote_backup_connections(id) ON DELETE CASCADE,
    created_at           timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (schedule_id, remote_connection_id)
);

CREATE INDEX idx_backup_schedule_full_remotes_remote
    ON backup_schedule_full_remotes (remote_connection_id);

CREATE TABLE local_backup_pushes (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    local_backup_id      uuid NOT NULL REFERENCES local_backups(id) ON DELETE RESTRICT,
    remote_connection_id uuid NOT NULL REFERENCES remote_backup_connections(id) ON DELETE RESTRICT,
    status               text NOT NULL CHECK (status IN ('pending', 'pushing', 'ok', 'failed')),
    pushed_at            timestamptz,
    error                text,
    remote_path          text,
    size_bytes           bigint,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now(),
    UNIQUE (local_backup_id, remote_connection_id)
);

CREATE INDEX idx_local_backup_pushes_local
    ON local_backup_pushes (local_backup_id);
CREATE INDEX idx_local_backup_pushes_remote
    ON local_backup_pushes (remote_connection_id);

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_local_backup_pushes_updated_at') THEN
        CREATE TRIGGER trg_local_backup_pushes_updated_at
            BEFORE UPDATE ON local_backup_pushes
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
END $$;

ALTER TABLE backup_schedules_full
    ADD COLUMN keep_local boolean NOT NULL DEFAULT true;

ALTER TABLE local_backups
    ADD COLUMN local_file_present boolean NOT NULL DEFAULT true;

INSERT INTO backup_schedule_full_remotes (schedule_id, remote_connection_id)
SELECT id, remote_connection_id
FROM backup_schedules_full
WHERE remote_connection_id IS NOT NULL;

ALTER TABLE backup_schedules_full DROP COLUMN remote_connection_id;
