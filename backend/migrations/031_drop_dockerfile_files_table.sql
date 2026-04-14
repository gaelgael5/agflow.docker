-- 031_drop_dockerfile_files_table.sql
-- File storage fully migrated to filesystem ({AGFLOW_DATA_DIR}/{slug}/).
-- The dockerfile_files table is no longer used by any service.
DROP TABLE IF EXISTS dockerfile_files;
