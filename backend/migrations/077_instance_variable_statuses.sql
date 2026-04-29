-- Status par variable d'instance (keep / clean / replace).
-- Indique à l'API de création d'instance de projet comment traiter chaque
-- variable au moment du déploiement :
--   keep    : valeur stockée utilisée, pas besoin de la fournir à l'API
--   clean   : l'utilisateur DOIT fournir la valeur à l'API
--   replace : valeur par défaut utilisée, override possible via l'API
-- Format : {"VAR_NAME": "keep"|"clean"|"replace"}
ALTER TABLE instances
    ADD COLUMN IF NOT EXISTS variable_statuses JSONB NOT NULL DEFAULT '{}'::jsonb;
