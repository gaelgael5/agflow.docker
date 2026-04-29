-- Phase 1 SaaS Runtimes : assignation user × machine, scalabilité par groupe,
-- nombre de copies effectif au runtime.
--
-- 1. Une machine peut être dédiée à un utilisateur pour un environnement donné.
--    Les machines admin/partagées restent sans owner (user_id NULL).
--    Contrainte : un user a au plus une machine par environnement.
--
-- 2. Le design d'un projet déclare quels groupes sont scalables (max_replicas > 1)
--    ou standards (max_replicas = 1, défaut).
--
-- 3. Au runtime, l'owner choisit combien de copies de chaque groupe il veut, dans
--    la borne définie par groups.max_replicas. replica_count = 0 = groupe non
--    sélectionné dans ce runtime (en pratique on n'insère pas la ligne plutôt
--    que de stocker 0 ; le check >= 0 reste pour cohérence avec d'éventuelles
--    futures évolutions).

ALTER TABLE infra_machines
    ADD COLUMN IF NOT EXISTS user_id     UUID REFERENCES users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS environment VARCHAR(50);

CREATE UNIQUE INDEX IF NOT EXISTS uniq_machine_user_env
    ON infra_machines(user_id, environment)
    WHERE user_id IS NOT NULL;

ALTER TABLE groups
    ADD COLUMN IF NOT EXISTS max_replicas INTEGER NOT NULL DEFAULT 1
    CHECK (max_replicas >= 1);

ALTER TABLE project_group_runtimes
    ADD COLUMN IF NOT EXISTS replica_count INTEGER NOT NULL DEFAULT 1
    CHECK (replica_count >= 0);
