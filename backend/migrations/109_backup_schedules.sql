-- 109_backup_schedules.sql — Planifications de backups (full cron + snapshot interval)

CREATE TABLE backup_schedules_full (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name                  text NOT NULL,
    cron_expr             text NOT NULL,
    remote_connection_id  uuid REFERENCES remote_backup_connections(id) ON DELETE SET NULL,
    retention_count       int  NOT NULL DEFAULT 10 CHECK (retention_count >= 1),
    enabled               boolean NOT NULL DEFAULT true,
    last_run_at           timestamptz,
    last_run_status       text CHECK (last_run_status IN ('ok', 'failed')),
    last_run_error        text,
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now(),
    created_by_user_id    uuid REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE backup_schedules_snapshot (
    id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name                  text NOT NULL,
    interval_amount       int  NOT NULL CHECK (interval_amount > 0),
    interval_unit         text NOT NULL CHECK (interval_unit IN ('minutes', 'hours')),
    remote_connection_id  uuid REFERENCES remote_backup_connections(id) ON DELETE SET NULL,
    retention_count       int  NOT NULL DEFAULT 24 CHECK (retention_count >= 1),
    enabled               boolean NOT NULL DEFAULT true,
    last_run_at           timestamptz,
    last_run_status       text CHECK (last_run_status IN ('ok', 'failed')),
    last_run_error        text,
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now(),
    created_by_user_id    uuid REFERENCES users(id) ON DELETE SET NULL
);

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_backup_schedules_full_updated_at') THEN
        CREATE TRIGGER trg_backup_schedules_full_updated_at
            BEFORE UPDATE ON backup_schedules_full
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_backup_schedules_snapshot_updated_at') THEN
        CREATE TRIGGER trg_backup_schedules_snapshot_updated_at
            BEFORE UPDATE ON backup_schedules_snapshot
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
END $$;

ALTER TABLE local_backups ADD COLUMN source_schedule_full_id     uuid REFERENCES backup_schedules_full(id)     ON DELETE SET NULL;
ALTER TABLE local_backups ADD COLUMN source_schedule_snapshot_id uuid REFERENCES backup_schedules_snapshot(id) ON DELETE SET NULL;
ALTER TABLE local_backups ADD CONSTRAINT local_backups_source_single CHECK (
    (source_schedule_full_id IS NULL) OR (source_schedule_snapshot_id IS NULL)
);

CREATE INDEX idx_local_backups_source_full     ON local_backups(source_schedule_full_id, created_at DESC)     WHERE source_schedule_full_id     IS NOT NULL;
CREATE INDEX idx_local_backups_source_snapshot ON local_backups(source_schedule_snapshot_id, created_at DESC) WHERE source_schedule_snapshot_id IS NOT NULL;
