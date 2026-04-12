-- 022_users.sql
CREATE TABLE IF NOT EXISTS users (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email       TEXT NOT NULL UNIQUE,
    name        TEXT NOT NULL DEFAULT '',
    avatar_url  TEXT NOT NULL DEFAULT '',
    role        TEXT NOT NULL DEFAULT 'user'
                CHECK (role IN ('admin', 'user')),
    scopes      TEXT[] NOT NULL DEFAULT '{}',
    status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'active', 'disabled')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    approved_at TIMESTAMPTZ,
    approved_by UUID REFERENCES users(id),
    last_login  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_status ON users(status);
