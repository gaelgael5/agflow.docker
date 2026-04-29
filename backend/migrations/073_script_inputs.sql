-- Variables d'entrée déclarées par un script shell.
-- Format de scripts.input_variables :
--   [{"name": "LXC_ID", "description": "Identifiant LXC", "default": "200"}]
--
-- Format de group_scripts.input_values (valeurs par liaison) :
--   {"LXC_ID": "114", "LXC_NAME": "agflow-node"}
--
-- Peut contenir des références ${ENV_VAR} qui seront résolues à l'exécution
-- contre le .env généré du déploiement.
--
-- Règles de déclenchement (trigger_rules) : conditions évaluées AVANT exécution.
-- Si une règle n'est pas satisfaite, le script est skipé. Format :
--   [{"variable": "FOO", "op": "equals", "value": "bar"},
--    {"variable": "BAZ", "op": "is_null"}]
-- Opérateurs supportés : equals, not_equals, is_null.

ALTER TABLE scripts
    ADD COLUMN IF NOT EXISTS input_variables JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE group_scripts
    ADD COLUMN IF NOT EXISTS input_values JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE group_scripts
    ADD COLUMN IF NOT EXISTS trigger_rules JSONB NOT NULL DEFAULT '[]'::jsonb;
