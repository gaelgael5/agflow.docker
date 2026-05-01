-- 087_swarm_clusters.sql — Modélisation cluster Swarm + extension machines

-- ── Nouvelle table : cluster Swarm comme entité 1st-class ──────────────
CREATE TABLE IF NOT EXISTS infra_swarm_clusters (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR NOT NULL UNIQUE,
    manager_addr VARCHAR NOT NULL,
    join_token_worker_encrypted TEXT NOT NULL,
    join_token_manager_encrypted TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_infra_swarm_clusters_updated_at') THEN
        CREATE TRIGGER trg_infra_swarm_clusters_updated_at
            BEFORE UPDATE ON infra_swarm_clusters
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
END $$;

-- ── Extension infra_machines : 8 colonnes 1st-class + 2 colonnes Swarm membership ──
-- NOTE: 'ctid' est un nom de colonne systeme reserve par PostgreSQL (tuple id),
--       on stocke le CTID Proxmox sous 'lxc_ctid' pour eviter le conflit.
ALTER TABLE infra_machines ADD COLUMN IF NOT EXISTS lxc_ctid INTEGER;
ALTER TABLE infra_machines ADD COLUMN IF NOT EXISTS distro VARCHAR(64);
ALTER TABLE infra_machines ADD COLUMN IF NOT EXISTS ip_type VARCHAR(16);
ALTER TABLE infra_machines ADD COLUMN IF NOT EXISTS docker_version VARCHAR(32);
ALTER TABLE infra_machines ADD COLUMN IF NOT EXISTS compose_version VARCHAR(32);
ALTER TABLE infra_machines ADD COLUMN IF NOT EXISTS swarm_ready BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE infra_machines ADD COLUMN IF NOT EXISTS swarm_mode VARCHAR(16);
ALTER TABLE infra_machines ADD COLUMN IF NOT EXISTS tun_device_present BOOLEAN;
ALTER TABLE infra_machines ADD COLUMN IF NOT EXISTS swarm_cluster_id UUID;
ALTER TABLE infra_machines ADD COLUMN IF NOT EXISTS swarm_node_role VARCHAR(16);

-- FK vers infra_swarm_clusters (idempotent)
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'infra_machines_swarm_cluster_id_fkey'
    ) THEN
        ALTER TABLE infra_machines
            ADD CONSTRAINT infra_machines_swarm_cluster_id_fkey
            FOREIGN KEY (swarm_cluster_id) REFERENCES infra_swarm_clusters(id) ON DELETE SET NULL;
    END IF;
END $$;

-- CHECK : role doit être manager|worker|NULL
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'swarm_node_role_chk'
    ) THEN
        ALTER TABLE infra_machines
            ADD CONSTRAINT swarm_node_role_chk
            CHECK (swarm_node_role IN ('manager', 'worker') OR swarm_node_role IS NULL);
    END IF;
END $$;

-- CHECK : cohérence (cluster_id NULL ⇔ role NULL)
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'swarm_membership_consistent_chk'
    ) THEN
        ALTER TABLE infra_machines
            ADD CONSTRAINT swarm_membership_consistent_chk
            CHECK ((swarm_cluster_id IS NULL AND swarm_node_role IS NULL)
                OR (swarm_cluster_id IS NOT NULL AND swarm_node_role IS NOT NULL));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_infra_machines_swarm_cluster
    ON infra_machines (swarm_cluster_id) WHERE swarm_cluster_id IS NOT NULL;

-- ── Seed : 3 nouvelles category_actions sur catégorie 'service' ────────
INSERT INTO infra_category_actions (category, name, is_required) VALUES
    ('service', 'swarm_init',  FALSE),
    ('service', 'swarm_join',  FALSE),
    ('service', 'swarm_leave', FALSE)
ON CONFLICT (category, name) DO NOTHING;
