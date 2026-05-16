-- 105_harpocrate_vaults.sql — Coffres Harpocrate configurables côté DB
--
-- Stocke les credentials des coffres Harpocrate utilisés par l'app. Plusieurs
-- coffres peuvent coexister ; un seul est marqué `is_default = true` à un
-- instant donné (partial unique index).
--
-- La clé API est chiffrée au repos via `pgcrypto.PGP_SYM_ENCRYPT` avec une
-- passphrase issue de l'env var `HARPOCRATE_DEK` (Data Encryption Key). La
-- lecture via `PGP_SYM_DECRYPT(api_key_encrypted, $1)` se fait côté service
-- Python (asyncpg) au moment de construire le `VaultClient`.
--
-- pgcrypto est déjà activé dans 001_init.sql ; pas besoin de re-CREATE.

CREATE TABLE IF NOT EXISTS harpocrate_vaults (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name varchar NOT NULL UNIQUE,
    base_url varchar NOT NULL,
    api_key_id varchar NOT NULL,
    api_key_encrypted bytea NOT NULL,
    is_default boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- Un seul coffre marqué default à la fois. Plusieurs coffres avec
-- is_default=false sont OK (l'index partiel ne contraint que les true).
CREATE UNIQUE INDEX IF NOT EXISTS harpocrate_vaults_default_unique
    ON harpocrate_vaults (is_default)
    WHERE is_default;

-- Trigger updated_at (fonction `set_updated_at` définie dans 001_init.sql)
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'trg_harpocrate_vaults_updated_at'
    ) THEN
        CREATE TRIGGER trg_harpocrate_vaults_updated_at
            BEFORE UPDATE ON harpocrate_vaults
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
END $$;
