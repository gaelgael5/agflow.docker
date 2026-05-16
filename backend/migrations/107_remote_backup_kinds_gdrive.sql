-- 107_remote_backup_kinds_gdrive.sql — Ajoute 'gdrive' au CHECK kind
--
-- Nouveau provider OAuth Google Drive pour les remote backups. Voir spec
-- docs/superpowers/specs/2026-05-16-google-drive-remote-backup-design.md.

ALTER TABLE remote_backup_connections
    DROP CONSTRAINT remote_backup_connections_kind_check;

ALTER TABLE remote_backup_connections
    ADD CONSTRAINT remote_backup_connections_kind_check
    CHECK (kind IN ('sftp', 's3', 'ftps', 'gdrive'));
