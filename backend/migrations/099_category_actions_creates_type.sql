ALTER TABLE infra_categories
    DROP COLUMN IF EXISTS is_vps;

ALTER TABLE infra_category_actions
    ADD COLUMN IF NOT EXISTS creates_named_type_id UUID
        REFERENCES infra_named_types(id) ON DELETE SET NULL;
