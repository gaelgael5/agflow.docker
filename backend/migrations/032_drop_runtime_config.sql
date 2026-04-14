-- 032_drop_runtime_config.sql
-- runtime_config was never used functionally — always empty {}.
ALTER TABLE roles DROP COLUMN IF EXISTS runtime_config;
