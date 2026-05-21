-- 120_scripts_output_variables.sql
-- Variables de sortie déclarées par un script (mirror de scripts.input_variables).
--
-- Convention d'usage (V1 — déclaratif uniquement) :
--   Chaque entrée déclare une valeur que le script promet de renvoyer dans la
--   dernière ligne JSON de son stdout (même mécanisme que `add_node` :
--   _parse_last_json côté project_deployments).
--
--   {
--     "name":        "HOSTNAME",
--     "description": "Hostname public assigné par cloudflare-manager",
--     "path":        "result.hostname"   // dot-path dans le JSON parsé
--   }
--
-- La consommation (injection automatique dans le .env du déploiement, alertes
-- sur valeurs manquantes côté UI de paramétrage projet) sera implémentée
-- dans un chantier séparé. Ici on stocke uniquement la déclaration.

ALTER TABLE scripts
    ADD COLUMN IF NOT EXISTS output_variables JSONB NOT NULL DEFAULT '[]'::jsonb;
