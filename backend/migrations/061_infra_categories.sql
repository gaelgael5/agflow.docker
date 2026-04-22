-- Catégories dynamiques pour infra_types
-- Remplace la contrainte CHECK (type IN ('platform','service')) par une FK
-- vers une nouvelle table infra_categories pilotée par l'utilisateur via l'UI.

CREATE TABLE IF NOT EXISTS infra_categories (
    name VARCHAR PRIMARY KEY
);

INSERT INTO infra_categories (name) VALUES
    ('platform'),
    ('service')
ON CONFLICT (name) DO NOTHING;

DO $$
DECLARE
    check_name TEXT;
BEGIN
    SELECT conname INTO check_name
    FROM pg_constraint
    WHERE conrelid = 'infra_types'::regclass
      AND contype = 'c'
      AND pg_get_constraintdef(oid) ILIKE '%type = ANY%'
    LIMIT 1;

    IF check_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE infra_types DROP CONSTRAINT %I', check_name);
    END IF;
END $$;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'infra_types_type_fkey'
          AND conrelid = 'infra_types'::regclass
    ) THEN
        ALTER TABLE infra_types
            ADD CONSTRAINT infra_types_type_fkey
            FOREIGN KEY (type) REFERENCES infra_categories(name)
            ON UPDATE CASCADE ON DELETE RESTRICT;
    END IF;
END $$;
