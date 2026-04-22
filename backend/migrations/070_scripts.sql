-- Scripts shell (stockés en BDD) + liaison vers les groupes avec
-- contexte d'exécution (machine cible, timing, ordre, mapping env).

CREATE TABLE IF NOT EXISTS scripts (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name         VARCHAR UNIQUE NOT NULL,
    description  TEXT NOT NULL DEFAULT '',
    content      TEXT NOT NULL DEFAULT '',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS group_scripts (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    group_id     UUID NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    script_id    UUID NOT NULL REFERENCES scripts(id) ON DELETE CASCADE,
    machine_id   UUID NOT NULL REFERENCES infra_machines(id) ON DELETE RESTRICT,
    timing       VARCHAR NOT NULL CHECK (timing IN ('before', 'after')),
    position     INTEGER NOT NULL DEFAULT 0,
    env_mapping  JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_group_scripts_group_timing
    ON group_scripts(group_id, timing, position);
CREATE INDEX IF NOT EXISTS idx_group_scripts_script_id
    ON group_scripts(script_id);
CREATE INDEX IF NOT EXISTS idx_group_scripts_machine_id
    ON group_scripts(machine_id);

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_scripts_updated_at') THEN
        CREATE TRIGGER trg_scripts_updated_at
            BEFORE UPDATE ON scripts
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_group_scripts_updated_at') THEN
        CREATE TRIGGER trg_group_scripts_updated_at
            BEFORE UPDATE ON group_scripts
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
END $$;
