-- 112_drop_snapshot_schedules.sql
-- Drop le système snapshot remplacé par PITR (cf. spec docs/superpowers/specs/2026-05-19-pitr-design.md)

ALTER TABLE local_backups DROP CONSTRAINT IF EXISTS local_backups_source_single;
ALTER TABLE local_backups DROP COLUMN IF EXISTS source_schedule_snapshot_id;
DROP TABLE IF EXISTS backup_schedules_snapshot;
