-- 007_dockerfiles — Module 1 dockerfiles (CLI agent image definitions)
CREATE TABLE IF NOT EXISTS dockerfiles (
    id              TEXT PRIMARY KEY,
    display_name    TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    parameters      JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dockerfiles_display_name ON dockerfiles(display_name);
