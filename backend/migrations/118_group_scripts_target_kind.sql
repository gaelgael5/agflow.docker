-- 118_group_scripts_target_kind.sql
-- Ajoute la notion de "cible dynamique" aux scripts pré/post démarrage d'un groupe.
--
-- Avant : group_scripts.machine_id est obligatoire (UUID fixe vers infra_machines).
-- Après :
--   * target_kind ∈ {'fixed_machine', 'deployment_host'}
--   * machine_id devient nullable
--   * Si target_kind = 'fixed_machine', machine_id doit être renseigné (CHECK)
--   * Si target_kind = 'deployment_host', machine_id est ignoré → résolu au runtime
--     vers la machine assignée au groupe (group.machine_id).
--
-- Le runtime fait l'aiguillage. V1 = compose standalone seulement ; le mode
-- swarm sera traité dans un chantier séparé (cf. memory project_swarm_open_questions).

ALTER TABLE group_scripts
    ADD COLUMN IF NOT EXISTS target_kind VARCHAR(32) NOT NULL DEFAULT 'fixed_machine'
        CHECK (target_kind IN ('fixed_machine', 'deployment_host'));

ALTER TABLE group_scripts
    ALTER COLUMN machine_id DROP NOT NULL;

ALTER TABLE group_scripts
    ADD CONSTRAINT group_scripts_machine_id_required_for_fixed
        CHECK (target_kind = 'deployment_host' OR machine_id IS NOT NULL);
