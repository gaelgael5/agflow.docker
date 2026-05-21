-- 121_infra_env_variables.sql
-- Variables d'environnement déclarées par variante typée (infra_named_types)
-- et remplies par chaque machine (infra_machines).
--
-- Flux : variante déclare les noms (contrat) → machine remplit les valeurs.
-- La valeur peut être :
--   - littérale : "my-hostname"
--   - référence vault : "${vault://BACKUPS:PGPASSWORD}"
--   - référence env OS : "${env://HOME}"
-- Résolution faite au runtime par platform_secrets_service.resolve_platform_refs.

CREATE TABLE IF NOT EXISTS infra_named_type_env_vars (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    named_type_id UUID NOT NULL REFERENCES infra_named_types(id) ON DELETE CASCADE,
    name          VARCHAR(128) NOT NULL,
    description   TEXT NOT NULL DEFAULT '',
    position      INT NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (named_type_id, name)
);

CREATE INDEX IF NOT EXISTS idx_nt_env_vars_named_type
    ON infra_named_type_env_vars(named_type_id);

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'trg_nt_env_vars_updated_at'
    ) THEN
        CREATE TRIGGER trg_nt_env_vars_updated_at
            BEFORE UPDATE ON infra_named_type_env_vars
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS infra_machine_env_vars (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    machine_id            UUID NOT NULL REFERENCES infra_machines(id) ON DELETE CASCADE,
    named_type_env_var_id UUID NOT NULL REFERENCES infra_named_type_env_vars(id) ON DELETE CASCADE,
    value                 TEXT NOT NULL DEFAULT '',
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (machine_id, named_type_env_var_id)
);

CREATE INDEX IF NOT EXISTS idx_machine_env_vars_machine
    ON infra_machine_env_vars(machine_id);

CREATE INDEX IF NOT EXISTS idx_machine_env_vars_contract
    ON infra_machine_env_vars(named_type_env_var_id);

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'trg_machine_env_vars_updated_at'
    ) THEN
        CREATE TRIGGER trg_machine_env_vars_updated_at
            BEFORE UPDATE ON infra_machine_env_vars
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
END $$;
