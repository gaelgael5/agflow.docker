-- Suppression de la table infra_types : plus aucune FK entrante depuis les
-- migrations 067 (infra_named_types.type_id → infra_categories) et 068
-- (infra_named_types.sub_type_id auto-référence). Le concept "type" entre
-- catégorie et variante devient redondant.
DROP TABLE IF EXISTS infra_types CASCADE;
