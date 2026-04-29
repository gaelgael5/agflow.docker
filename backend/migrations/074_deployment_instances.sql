-- Pivot historique des déploiements d'instances.
-- Chaque ligne = une instance poussée sur une machine lors d'un déploiement donné.
-- Permet : (1) historique complet "quand cette instance a-t-elle été déployée"
--          (2) savoir sur quelle machine cibler les commandes runtime
--              (status / start / stop)
CREATE TABLE IF NOT EXISTS deployment_instances (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    deployment_id   UUID NOT NULL REFERENCES project_deployments(id) ON DELETE CASCADE,
    instance_id     UUID NOT NULL REFERENCES instances(id) ON DELETE CASCADE,
    machine_id      UUID REFERENCES infra_machines(id) ON DELETE SET NULL,
    deployed_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    success         BOOLEAN,
    error_message   TEXT
);

CREATE INDEX IF NOT EXISTS idx_deployment_instances_deployment
    ON deployment_instances(deployment_id);
CREATE INDEX IF NOT EXISTS idx_deployment_instances_instance_recent
    ON deployment_instances(instance_id, deployed_at DESC);
CREATE INDEX IF NOT EXISTS idx_deployment_instances_machine
    ON deployment_instances(machine_id) WHERE machine_id IS NOT NULL;
