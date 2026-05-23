-- 123_restore_jobs.sql
-- Jobs de restauration éphémères créés par le wizard de restauration.
-- Aucune FK — les jobs sont indépendants du reste du schéma.

CREATE TABLE restore_jobs (
    id            UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    status        TEXT         NOT NULL DEFAULT 'running',  -- running | done | failed
    log           TEXT         NOT NULL DEFAULT '',
    created_at    timestamp with time zone  NOT NULL DEFAULT now(),
    completed_at  timestamp with time zone
);
