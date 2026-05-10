ALTER TABLE infra_categories
    ADD COLUMN IF NOT EXISTS visible_in_machines BOOLEAN NOT NULL DEFAULT false;
