-- 117_groups_swarm_template_and_docker_filetype.sql
-- V1 du chantier "templates compose/swarm" :
--   * nouveau type de fichier Jinja2 : 'docker' (extension .docker.j2)
--     destiné aux fichiers docker-compose / stack swarm rendus par Jinja2.
--   * nouvelle colonne groups.swarm_template_slug pour distinguer le template
--     compose (docker_standalone) du template swarm (docker_swarm).
-- k8s/k3s ne sont PAS ajoutés ici — chantier séparé quand on définira leur format.

INSERT INTO template_file_types (key, label, sort_order)
VALUES ('docker', 'Docker compose / swarm (.docker)', 2)
ON CONFLICT (key) DO NOTHING;

ALTER TABLE groups
    ADD COLUMN IF NOT EXISTS swarm_template_slug VARCHAR;
