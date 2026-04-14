-- 034_drop_role_documents_table.sql
-- Documents fully on disk at {AGFLOW_DATA_DIR}/roles/{role_id}/{section}/{name}.md
-- UUIDs computed deterministically as UUID5(role_id:section:name).
DROP TABLE IF EXISTS role_documents;
