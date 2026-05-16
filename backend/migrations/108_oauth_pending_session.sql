-- 108_oauth_pending_session.sql — Table pour le round-trip OAuth
--
-- Persiste l'état OAuth entre `/start` (redirection Google) et `/callback`.
-- TTL court (10 min). Le `client_secret` est chiffré pgcrypto via HARPOCRATE_DEK
-- pendant le round-trip ; au callback il est déchiffré, utilisé pour fetch_token,
-- puis re-chiffré dans Harpocrate au path final remote_backups/<id>/oauth.
-- Worker `oauth_pending_reaper` purge les expirés/consumed (tick 5min).

CREATE TABLE oauth_pending_session (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    state                    text NOT NULL UNIQUE,
    kind                     text NOT NULL CHECK (kind IN ('gdrive')),
    actor_user_id            uuid REFERENCES users(id) ON DELETE SET NULL,
    redirect_uri             text NOT NULL,
    form_data                jsonb NOT NULL DEFAULT '{}'::jsonb,
    client_secret_encrypted  bytea NOT NULL,
    expires_at               timestamptz NOT NULL,
    consumed_at              timestamptz,
    created_at               timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_oauth_pending_expires_at
    ON oauth_pending_session(expires_at)
    WHERE consumed_at IS NULL;
