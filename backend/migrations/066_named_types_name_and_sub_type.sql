-- 1. Nom humain sur les variantes typées (infra_named_types)
-- 2. sub_type_id pointait vers infra_named_types (auto-ref) → désormais vers
--    infra_types(id). Le sous-type d'une variante VPS (Proxmox) est un
--    type enfant (LXC) et pas une autre variante.
--
-- La table est vide à ce stade (créée en 064, non peuplée), donc on peut
-- modifier sans backfill.

-- Drop de l'auto-FK (nom standard Postgres : <table>_<col>_fkey)
ALTER TABLE infra_named_types
    DROP CONSTRAINT IF EXISTS infra_named_types_sub_type_id_fkey;

-- Nouvelle FK vers infra_types
ALTER TABLE infra_named_types
    ADD CONSTRAINT infra_named_types_sub_type_id_fkey FOREIGN KEY (sub_type_id)
    REFERENCES infra_types(id) ON DELETE SET NULL;

-- Colonne name (label humain de la variante)
ALTER TABLE infra_named_types
    ADD COLUMN IF NOT EXISTS name VARCHAR NOT NULL DEFAULT '';
