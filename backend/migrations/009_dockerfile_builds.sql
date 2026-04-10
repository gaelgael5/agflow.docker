-- 009_dockerfile_builds — build history + logs per dockerfile
CREATE TABLE IF NOT EXISTS dockerfile_builds (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    dockerfile_id   TEXT NOT NULL REFERENCES dockerfiles(id) ON DELETE CASCADE,
    content_hash    TEXT NOT NULL,
    image_tag       TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'running', 'success', 'failed')),
    logs            TEXT NOT NULL DEFAULT '',
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS idx_dockerfile_builds_dockerfile
    ON dockerfile_builds(dockerfile_id, started_at DESC);
