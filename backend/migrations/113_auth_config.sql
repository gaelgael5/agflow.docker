-- 113_auth_config.sql — Configuration d'authentification (singleton)

CREATE TABLE auth_config (
    id                          int PRIMARY KEY CHECK (id = 1),
    mode                        text NOT NULL DEFAULT 'local'
                                CHECK (mode IN ('local', 'keycloak')),
    keycloak_url                text NOT NULL DEFAULT '',
    keycloak_realm              text NOT NULL DEFAULT '',
    keycloak_client_id          text NOT NULL DEFAULT '',
    keycloak_client_secret_ref  text NOT NULL DEFAULT '',
    vault_name                  text NOT NULL DEFAULT 'default',
    updated_at                  timestamptz NOT NULL DEFAULT now(),
    updated_by_user_id          uuid REFERENCES users(id) ON DELETE SET NULL
);

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_auth_config_updated_at') THEN
        CREATE TRIGGER trg_auth_config_updated_at
            BEFORE UPDATE ON auth_config
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
END $$;

INSERT INTO auth_config (id, mode) VALUES (1, 'local') ON CONFLICT (id) DO NOTHING;
