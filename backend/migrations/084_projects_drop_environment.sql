-- Suppression de la notion d'environnement sur les projets.
-- L'enum dev/staging/prod était purement cosmétique et n'était référencé
-- par aucune autre table.

ALTER TABLE projects DROP COLUMN IF EXISTS environment;
