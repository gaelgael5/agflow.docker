-- Scripts : distinguer les langages (shell vs jinja2 pour compose rendering).
-- Groupes : référence optionnelle vers un script jinja2 qui génère le compose.

ALTER TABLE scripts
    ADD COLUMN IF NOT EXISTS language VARCHAR NOT NULL DEFAULT 'shell'
        CHECK (language IN ('shell', 'jinja2'));

ALTER TABLE groups
    ADD COLUMN IF NOT EXISTS compose_script_id UUID
        REFERENCES scripts(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_groups_compose_script_id
    ON groups(compose_script_id)
    WHERE compose_script_id IS NOT NULL;
