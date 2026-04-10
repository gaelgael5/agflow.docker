-- 008_dockerfile_files — multiple files per dockerfile (flat, no directory nesting)
CREATE TABLE IF NOT EXISTS dockerfile_files (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    dockerfile_id   TEXT NOT NULL REFERENCES dockerfiles(id) ON DELETE CASCADE,
    path            TEXT NOT NULL,
    content         TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (dockerfile_id, path)
);

CREATE INDEX IF NOT EXISTS idx_dockerfile_files_dockerfile ON dockerfile_files(dockerfile_id);
