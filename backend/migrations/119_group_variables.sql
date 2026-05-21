-- 119_group_variables.sql
-- Variables globales partagées au niveau d'un groupe.
--
-- Cas d'usage : définir une fois `PUBLIC_HOSTNAME = outline.yoops.org`
-- au niveau du groupe, et la consommer à la fois :
--   * dans la recette du produit (env_template: URL = "https://${PUBLIC_HOSTNAME}")
--   * dans les scripts pré/post démarrage (input_value = "${PUBLIC_HOSTNAME}")
--
-- Au Generate, project_deployments_service injecte ces variables dans le .env
-- du déploiement (après résolution des éventuelles refs ${vault://...} /
-- ${env://...} qu'elles contiennent).
--
-- `name` :  identifiant `UPPER_SNAKE` (validé applicativement, pas par CHECK SQL
--           — on garde la liberté pour `name` court de type alias).
-- `value` : valeur littérale OU référence déclarative (`${vault://...:path}`,
--           `${env://...}`). La résolution est faite par le moteur, pas par la DB.

CREATE TABLE IF NOT EXISTS group_variables (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_id    UUID NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    name        VARCHAR(128) NOT NULL,
    value       TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (group_id, name)
);

CREATE INDEX IF NOT EXISTS idx_group_variables_group_id ON group_variables (group_id);

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_group_variables_updated_at') THEN
        CREATE TRIGGER trg_group_variables_updated_at
            BEFORE UPDATE ON group_variables
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
END $$;
