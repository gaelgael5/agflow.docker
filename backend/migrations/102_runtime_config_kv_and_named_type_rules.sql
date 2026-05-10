-- Transforme runtime_config en store key/value avec contraintes de valeurs (filter).
-- Crée infra_named_type_rules pour les règles d'affichage des variantes typées.

-- 1. Ajouter les nouvelles colonnes
ALTER TABLE runtime_config
    ADD COLUMN IF NOT EXISTS key      VARCHAR(64),
    ADD COLUMN IF NOT EXISTS value    VARCHAR(256),
    ADD COLUMN IF NOT EXISTS filter   VARCHAR(512);

-- 2. Migrer la ligne la plus récente (mode → key='mode')
DO $$
DECLARE v_mode VARCHAR;
BEGIN
    SELECT mode INTO v_mode FROM runtime_config ORDER BY id DESC LIMIT 1;
    IF v_mode IS NOT NULL THEN
        UPDATE runtime_config
        SET key    = 'mode',
            value  = v_mode,
            filter = 'docker_standalone|docker_swarm|k3s|k8s'
        WHERE id = (SELECT MAX(id) FROM runtime_config);
        -- Supprimer les lignes orphelines (anciennes détections)
        DELETE FROM runtime_config WHERE key IS NULL;
    END IF;
END $$;

-- 3. Contraindre les colonnes et supprimer l'ancienne colonne mode
ALTER TABLE runtime_config ALTER COLUMN key   SET NOT NULL;
ALTER TABLE runtime_config ALTER COLUMN value SET NOT NULL;
ALTER TABLE runtime_config DROP COLUMN IF EXISTS mode;

-- 4. Unicité par clef (une seule valeur courante par clef)
ALTER TABLE runtime_config
    ADD CONSTRAINT runtime_config_key_unique UNIQUE (key);

-- 5. Table des règles d'affichage par variante typée
CREATE TABLE IF NOT EXISTS infra_named_type_rules (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    named_type_id  UUID        NOT NULL REFERENCES infra_named_types(id) ON DELETE CASCADE,
    key            VARCHAR(64) NOT NULL,
    value          VARCHAR(256) NOT NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (named_type_id, key)
);
