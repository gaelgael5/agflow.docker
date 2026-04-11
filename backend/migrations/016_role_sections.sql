-- 016_role_sections — dynamic categories for role documents
-- Replace the hardcoded CHECK constraint on role_documents.section with a
-- proper FK to a new role_sections table, allowing arbitrary custom
-- categories per role while keeping roles/missions/competences as protected
-- natives.

CREATE TABLE IF NOT EXISTS role_sections (
    role_id      TEXT NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    display_name TEXT NOT NULL,
    is_native    BOOLEAN NOT NULL DEFAULT FALSE,
    position     INTEGER NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (role_id, name)
);

CREATE INDEX IF NOT EXISTS idx_role_sections_role_pos
    ON role_sections(role_id, position);

-- Backfill native sections for every existing role
INSERT INTO role_sections (role_id, name, display_name, is_native, position)
SELECT r.id, 'roles', 'Rôles', TRUE, 0 FROM roles r
ON CONFLICT (role_id, name) DO NOTHING;

INSERT INTO role_sections (role_id, name, display_name, is_native, position)
SELECT r.id, 'missions', 'Missions', TRUE, 1 FROM roles r
ON CONFLICT (role_id, name) DO NOTHING;

INSERT INTO role_sections (role_id, name, display_name, is_native, position)
SELECT r.id, 'competences', 'Compétences', TRUE, 2 FROM roles r
ON CONFLICT (role_id, name) DO NOTHING;

-- Drop the legacy CHECK constraint that hardcoded the 3 section names
ALTER TABLE role_documents DROP CONSTRAINT IF EXISTS role_documents_section_check;

-- Enforce that every document belongs to an existing section for its role.
-- ON DELETE CASCADE: deleting a section also removes its documents — the
-- service layer blocks this by refusing to delete non-empty sections.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'role_documents_section_fk'
          AND conrelid = 'role_documents'::regclass
    ) THEN
        ALTER TABLE role_documents
            ADD CONSTRAINT role_documents_section_fk
            FOREIGN KEY (role_id, section)
            REFERENCES role_sections(role_id, name)
            ON DELETE CASCADE
            ON UPDATE CASCADE;
    END IF;
END $$;
