-- infra_named_types :
--  - sub_type_id repasse en self-référence (UUID → infra_named_types.id).
--    Une variante VPS (ex. Proxmox-DC1) pointe directement vers la variante
--    enfant à provisionner (ex. LXC-prod).
--  - creation_url supprimée : l'action « create » devient une action de
--    catégorie standard (infra_category_actions) avec son URL dans
--    infra_named_type_actions, exactement comme destroy ou install.
--
-- Table vide à ce stade, on peut recréer les colonnes sans backfill.

DELETE FROM infra_named_types;

ALTER TABLE infra_named_types
    DROP CONSTRAINT IF EXISTS infra_named_types_sub_type_id_fkey;
ALTER TABLE infra_named_types DROP COLUMN sub_type_id CASCADE;
ALTER TABLE infra_named_types DROP COLUMN IF EXISTS creation_url;

ALTER TABLE infra_named_types
    ADD COLUMN sub_type_id UUID
    REFERENCES infra_named_types(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_infra_named_types_sub_type_id
    ON infra_named_types(sub_type_id) WHERE sub_type_id IS NOT NULL;
