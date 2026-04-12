-- 023_user_identities.sql
CREATE TABLE IF NOT EXISTS user_identities (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider    TEXT NOT NULL,
    subject     TEXT NOT NULL,
    email       TEXT,
    raw_claims  JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (provider, subject)
);

CREATE INDEX IF NOT EXISTS idx_user_identities_user ON user_identities(user_id);
CREATE INDEX IF NOT EXISTS idx_user_identities_lookup ON user_identities(provider, subject);
