-- Remplace creates_named_type_id (ref directe) par creates_category (ref catégorie)
-- sur infra_category_actions, et ajoute creates_named_type_id sur infra_named_type_actions
-- pour permettre la sélection du type précis filtré par cette catégorie.

ALTER TABLE infra_category_actions
    DROP COLUMN IF EXISTS creates_named_type_id;

ALTER TABLE infra_category_actions
    ADD COLUMN IF NOT EXISTS creates_category VARCHAR
        REFERENCES infra_categories(name) ON DELETE SET NULL;

ALTER TABLE infra_named_type_actions
    ADD COLUMN IF NOT EXISTS creates_named_type_id UUID
        REFERENCES infra_named_types(id) ON DELETE SET NULL;
