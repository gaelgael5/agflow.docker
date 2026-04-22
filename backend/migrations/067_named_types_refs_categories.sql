-- infra_named_types : type_id et sub_type_id pointent désormais vers
-- infra_categories(name) au lieu d'infra_types(id).
-- L'intermédiaire infra_types devient facultatif (plus référencé par named_types).
--
-- Table vide à ce stade (migration 066 vient de la restructurer, aucune entrée
-- utilisateur via UI entre les deux). On purge par sécurité et on recrée
-- les colonnes en VARCHAR.

DELETE FROM infra_named_types;

ALTER TABLE infra_named_types
    DROP CONSTRAINT IF EXISTS infra_named_types_type_id_fkey;
ALTER TABLE infra_named_types
    DROP CONSTRAINT IF EXISTS infra_named_types_sub_type_id_fkey;

-- Drop des colonnes (CASCADE pour auto-drop des index associés)
ALTER TABLE infra_named_types DROP COLUMN type_id CASCADE;
ALTER TABLE infra_named_types DROP COLUMN sub_type_id CASCADE;

-- Nouvelles colonnes VARCHAR → infra_categories(name)
ALTER TABLE infra_named_types
    ADD COLUMN type_id VARCHAR NOT NULL
    REFERENCES infra_categories(name) ON UPDATE CASCADE ON DELETE RESTRICT;

ALTER TABLE infra_named_types
    ADD COLUMN sub_type_id VARCHAR
    REFERENCES infra_categories(name) ON UPDATE CASCADE ON DELETE SET NULL;

-- Recréation des index
CREATE INDEX IF NOT EXISTS idx_infra_named_types_type_id
    ON infra_named_types(type_id);
CREATE INDEX IF NOT EXISTS idx_infra_named_types_sub_type_id
    ON infra_named_types(sub_type_id) WHERE sub_type_id IS NOT NULL;
