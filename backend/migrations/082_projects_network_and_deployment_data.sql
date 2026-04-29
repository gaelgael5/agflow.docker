-- Ajoute le nom du réseau Docker au projet (référencé dans les services du compose)
-- et un champ JSONB pour stocker la structure de données pré-résolue affichée
-- dans le dialog "Déployer" (étape de validation avant génération du compose).

ALTER TABLE projects
    ADD COLUMN IF NOT EXISTS network VARCHAR NOT NULL DEFAULT 'agflow';

ALTER TABLE project_deployments
    ADD COLUMN IF NOT EXISTS generated_data JSONB NOT NULL DEFAULT '{}'::jsonb;
