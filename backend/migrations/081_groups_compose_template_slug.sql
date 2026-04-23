-- Annule la 080 : la génération compose utilise désormais le système filesystem
-- des templates (/app/data/templates/<slug>/<culture>.sh.j2), pas la table scripts.

-- Retire la FK vers scripts et la colonne
ALTER TABLE groups DROP COLUMN IF EXISTS compose_script_id;
DROP INDEX IF EXISTS idx_groups_compose_script_id;

-- Retire la colonne language (scripts redevient purement shell)
ALTER TABLE scripts DROP COLUMN IF EXISTS language;

-- Ajoute le pointeur vers un template filesystem (slug uniquement, stockage sur disque)
ALTER TABLE groups
    ADD COLUMN IF NOT EXISTS compose_template_slug VARCHAR;
