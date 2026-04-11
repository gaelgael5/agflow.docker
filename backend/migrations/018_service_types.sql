-- 018_service_types — CRUD-managed catalog of role service types
--
-- Replaces the hardcoded _ALLOWED_SERVICE_TYPES set in Python with a
-- real DB table so admins can add or remove types from the UI.
-- The 7 original types are seeded as is_native=TRUE so they stay
-- protected against accidental deletion.

CREATE TABLE IF NOT EXISTS service_types (
    name         TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    is_native    BOOLEAN NOT NULL DEFAULT FALSE,
    position     INTEGER NOT NULL DEFAULT 0,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO service_types (name, display_name, is_native, position) VALUES
    ('documentation', 'Documentation',      TRUE, 0),
    ('code',          'Code',               TRUE, 1),
    ('design',        'Maquette/Design',    TRUE, 2),
    ('automation',    'Automatisme',        TRUE, 3),
    ('task_list',     'Liste de tâches',    TRUE, 4),
    ('specs',         'Spécifications',     TRUE, 5),
    ('contract',      'Contrat',            TRUE, 6)
ON CONFLICT (name) DO NOTHING;
