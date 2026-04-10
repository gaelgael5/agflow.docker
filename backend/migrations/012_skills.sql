-- 012_skills — Module 3c local catalog of skills installed from registries
CREATE TABLE IF NOT EXISTS skills (
    id                   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    discovery_service_id TEXT NOT NULL REFERENCES discovery_services(id) ON DELETE CASCADE,
    skill_id             TEXT NOT NULL,
    name                 TEXT NOT NULL,
    description          TEXT NOT NULL DEFAULT '',
    content_md           TEXT NOT NULL DEFAULT '',
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (discovery_service_id, skill_id)
);
