-- Correctif migration 061 : la contrainte CHECK platform/service n'avait pas
-- été supprimée (le pattern ILIKE ne matchait pas "type::text = ANY" car
-- PostgreSQL ajoute le cast ::text dans pg_get_constraintdef).
-- Suppression directe par nom connu.

ALTER TABLE infra_types DROP CONSTRAINT IF EXISTS infra_types_type_check;
