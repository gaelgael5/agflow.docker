-- 029_files_to_disk.sql
-- File storage migrated from DB to filesystem. Existing files were exported
-- to {AGFLOW_DATA_DIR}/{slug}/ via a Python migration in the backend lifespan.
-- The dockerfile_files table is kept temporarily for reference but no longer used.
SELECT 1;
