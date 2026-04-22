-- M8 Infrastructure — restructuration majeure
--
-- 1. Fusionne infra_servers + infra_machines en une seule table infra_machines
--    (base = toutes les colonnes d'infra_servers).
-- 2. Introduit infra_named_types (variantes typées : Proxmox/SSH, LXC/SSH...)
--    + infra_named_type_actions (URLs des actions destroy/install/... par variante).
-- 3. Ajoute infra_machines_runs pour tracer chaque exécution de script.
-- 4. Passe infra_types en PK UUID, table vide au démarrage.
-- 5. Renomme groups.server_id → groups.machine_id.
-- 6. Wipe les données existantes (sauf infra_certificates + infra_categories
--    + infra_category_actions). L'utilisateur recrée manuellement via l'UI.
--
-- Tout est exécuté en une transaction (migrations runner). Rollback automatique
-- en cas d'erreur.

-- ─── 1. Wipe des JSONB référençant des serveurs (IDs orphelins) ─────
UPDATE project_deployments SET group_servers = '{}'::jsonb;

-- ─── 2. Drop des tables enfants + triggers associés ────────────────
DROP TABLE IF EXISTS infra_machine_metadata CASCADE;
DROP TABLE IF EXISTS infra_machines CASCADE;

-- ─── 3. Wipe infra_servers mais conserve la table (sera renommée) ──
DELETE FROM infra_servers;

-- ─── 4. Drop FK infra_servers.type → infra_types(name) + colonne ───
ALTER TABLE infra_servers DROP CONSTRAINT IF EXISTS infra_servers_type_fkey;
ALTER TABLE infra_servers DROP COLUMN IF EXISTS type;

-- ─── 5. Drop + recréation infra_types en PK UUID (vide) ────────────
DROP TABLE IF EXISTS infra_types CASCADE;
CREATE TABLE infra_types (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        VARCHAR UNIQUE NOT NULL,
    type        VARCHAR NOT NULL REFERENCES infra_categories(name)
                ON UPDATE CASCADE ON DELETE RESTRICT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ─── 6. Table infra_named_types ────────────────────────────────────
CREATE TABLE infra_named_types (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type_id          UUID NOT NULL REFERENCES infra_types(id) ON DELETE RESTRICT,
    sub_type_id      UUID REFERENCES infra_named_types(id) ON DELETE SET NULL,
    connection_type  VARCHAR NOT NULL,
    creation_url     VARCHAR,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ─── 7. Table infra_named_type_actions ─────────────────────────────
CREATE TABLE infra_named_type_actions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    named_type_id       UUID NOT NULL REFERENCES infra_named_types(id) ON DELETE CASCADE,
    category_action_id  UUID NOT NULL REFERENCES infra_category_actions(id) ON DELETE CASCADE,
    url                 VARCHAR NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (named_type_id, category_action_id)
);

-- ─── 8. Rename infra_servers → infra_machines ──────────────────────
ALTER TABLE infra_servers RENAME TO infra_machines;

-- Le trigger trg_infra_servers_updated_at suit automatiquement le rename,
-- mais on l'aligne pour la cohérence.
ALTER TRIGGER trg_infra_servers_updated_at ON infra_machines
    RENAME TO trg_infra_machines_updated_at;

-- ─── 9. Ajout de type_id UUID FK → infra_named_types ───────────────
ALTER TABLE infra_machines
    ADD COLUMN type_id UUID NOT NULL REFERENCES infra_named_types(id)
    ON DELETE RESTRICT;

-- ─── 10. groups.machine_id (ajout — server_id n'existe plus depuis 057) ────
-- Migration 056 a ajouté groups.server_id, puis 057 l'a supprimée. On réintroduit
-- la colonne sous son nouveau nom, pointant vers la table fusionnée.
ALTER TABLE groups DROP CONSTRAINT IF EXISTS groups_server_id_fkey;
ALTER TABLE groups
    ADD COLUMN IF NOT EXISTS machine_id UUID REFERENCES infra_machines(id)
    ON DELETE SET NULL;

-- ─── 11. Table infra_machines_runs ─────────────────────────────────
CREATE TABLE infra_machines_runs (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    machine_id     UUID NOT NULL REFERENCES infra_machines(id) ON DELETE CASCADE,
    action_id      UUID NOT NULL REFERENCES infra_named_type_actions(id) ON DELETE RESTRICT,
    started_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at    TIMESTAMPTZ,
    success        BOOLEAN,
    exit_code      INTEGER,
    error_message  TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ─── 12. Triggers updated_at ───────────────────────────────────────
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_infra_named_types_updated_at') THEN
        CREATE TRIGGER trg_infra_named_types_updated_at
            BEFORE UPDATE ON infra_named_types
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_infra_named_type_actions_updated_at') THEN
        CREATE TRIGGER trg_infra_named_type_actions_updated_at
            BEFORE UPDATE ON infra_named_type_actions
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
END $$;

-- ─── 13. Indices ───────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_infra_machines_parent_id
    ON infra_machines(parent_id) WHERE parent_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_infra_machines_type_id
    ON infra_machines(type_id);
CREATE INDEX IF NOT EXISTS idx_infra_machines_certificate_id
    ON infra_machines(certificate_id) WHERE certificate_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_infra_named_types_type_id
    ON infra_named_types(type_id);
CREATE INDEX IF NOT EXISTS idx_infra_named_types_sub_type_id
    ON infra_named_types(sub_type_id) WHERE sub_type_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_infra_named_type_actions_named_type
    ON infra_named_type_actions(named_type_id);
CREATE INDEX IF NOT EXISTS idx_infra_machines_runs_machine_started
    ON infra_machines_runs(machine_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_infra_machines_runs_action_id
    ON infra_machines_runs(action_id);
