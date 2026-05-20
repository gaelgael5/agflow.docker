-- 116_infra_categories_visible_in_machines_default_true.sql
-- Migration 101 avait introduit `infra_categories.visible_in_machines BOOLEAN NOT NULL DEFAULT false`.
-- Ce choix s'est révélé un opt-in silencieux : aucune catégorie n'apparaissait dans le picker
-- « Nouvelle machine → Type » tant qu'on n'allait pas la cocher à la main, sans aucun feedback UI.
-- On bascule en opt-out : DEFAULT true + on aligne les lignes existantes.

ALTER TABLE infra_categories
    ALTER COLUMN visible_in_machines SET DEFAULT true;

UPDATE infra_categories SET visible_in_machines = true WHERE visible_in_machines = false;
