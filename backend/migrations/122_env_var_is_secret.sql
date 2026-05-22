-- 122_env_var_is_secret.sql
-- Ajoute le flag is_secret sur infra_named_type_env_vars.
-- Permet de marquer une variable comme sensible (masquée dans les logs/UI).

ALTER TABLE infra_named_type_env_vars
    ADD COLUMN IF NOT EXISTS is_secret BOOLEAN NOT NULL DEFAULT FALSE;
