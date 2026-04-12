-- 025_api_keys.sql
CREATE TABLE IF NOT EXISTS api_keys (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id        UUID REFERENCES users(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    prefix          TEXT NOT NULL UNIQUE,
    key_hash        TEXT NOT NULL,
    scopes          TEXT[] NOT NULL DEFAULT '{}',
    rate_limit      INT NOT NULL DEFAULT 120,
    expires_at      TIMESTAMPTZ,
    revoked         BOOLEAN NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_api_keys_prefix ON api_keys(prefix);
CREATE INDEX IF NOT EXISTS idx_api_keys_owner ON api_keys(owner_id);
