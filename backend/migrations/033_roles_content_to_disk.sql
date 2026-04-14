-- 033_roles_content_to_disk.sql
-- Role content (display_name, description, identity_md, prompt_orchestrator_md,
-- service_types) migrated to filesystem at {AGFLOW_DATA_DIR}/roles/{role_id}/.
-- Document content (content_md) also on disk.
-- DB keeps only existence tracking (id, timestamps) and document metadata.
ALTER TABLE roles DROP COLUMN IF EXISTS display_name;
ALTER TABLE roles DROP COLUMN IF EXISTS description;
ALTER TABLE roles DROP COLUMN IF EXISTS service_types;
ALTER TABLE roles DROP COLUMN IF EXISTS identity_md;
ALTER TABLE roles DROP COLUMN IF EXISTS prompt_orchestrator_md;
ALTER TABLE role_documents DROP COLUMN IF EXISTS content_md;
