-- 004_role_documents — Module 2 documents per role (sections: roles, missions, competences)
CREATE TABLE IF NOT EXISTS role_documents (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    role_id     TEXT NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    section     TEXT NOT NULL
                CHECK (section IN ('roles', 'missions', 'competences')),
    parent_path TEXT NOT NULL DEFAULT '',
    name        TEXT NOT NULL,
    content_md  TEXT NOT NULL DEFAULT '',
    protected   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (role_id, section, parent_path, name)
);

CREATE INDEX IF NOT EXISTS idx_role_documents_role_section
    ON role_documents(role_id, section);
