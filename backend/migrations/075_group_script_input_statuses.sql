-- Status par variable au niveau de la liaison script↔groupe.
-- Format : {"VAR_NAME": "keep"|"clean"|"replace"}
-- - keep : la valeur stockée est utilisée, pas besoin de la fournir à l'API
-- - clean : l'utilisateur DOIT fournir la valeur à l'API de déploiement
-- - replace : valeur par défaut utilisée sauf override explicite à l'API
ALTER TABLE group_scripts
    ADD COLUMN IF NOT EXISTS input_statuses JSONB NOT NULL DEFAULT '{}'::jsonb;
