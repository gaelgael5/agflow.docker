-- M6 Supervision — colonnes d'activité sur agents_instances,
-- table platform_config pour les timeouts globaux, et defaults associés.

-- 1) Colonnes supervision sur agents_instances
ALTER TABLE agents_instances
    ADD COLUMN IF NOT EXISTS last_activity_at TIMESTAMPTZ NOT NULL DEFAULT now();

ALTER TABLE agents_instances
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'idle';

ALTER TABLE agents_instances
    ADD COLUMN IF NOT EXISTS error_message TEXT;

-- CHECK appliqué séparément pour être idempotent (pas de IF NOT EXISTS sur CHECK en pg16)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'agents_instances_status_chk'
    ) THEN
        ALTER TABLE agents_instances
            ADD CONSTRAINT agents_instances_status_chk
            CHECK (status IN ('idle','busy','error','destroyed'));
    END IF;
END$$;

CREATE INDEX IF NOT EXISTS idx_agents_instances_status_activity
    ON agents_instances (status, last_activity_at)
    WHERE destroyed_at IS NULL;

-- 2) Table platform_config (clé/valeur modifiable en UI pour les timeouts globaux)
CREATE TABLE IF NOT EXISTS platform_config (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 3) Defaults des timeouts supervision (en secondes)
INSERT INTO platform_config (key, value) VALUES
    ('session_idle_timeout_s',               '120'),
    ('agent_idle_timeout_s',                 '600'),
    ('supervision_reaper_interval_s',        '20'),
    ('supervision_reclaim_interval_s',       '15'),
    ('supervision_reclaim_stale_threshold_s','30')
ON CONFLICT (key) DO NOTHING;
