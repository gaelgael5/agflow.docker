-- Flag VPS sur les catégories d'infra : indique qu'une catégorie correspond
-- à un hébergeur VPS (vs services internes non-VPS).
ALTER TABLE infra_categories
    ADD COLUMN IF NOT EXISTS is_vps BOOLEAN NOT NULL DEFAULT false;
