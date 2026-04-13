-- 030_launched_tasks.sql
-- Tracks launched agent tasks. The container_id (Docker internal) is stored
-- but never exposed via the API — callers only see the agflow UUID.
CREATE TABLE IF NOT EXISTS launched_tasks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dockerfile_id   TEXT NOT NULL,
    container_id    TEXT,
    container_name  TEXT,
    instruction     TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'running', 'success', 'failure', 'stopped', 'error')),
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ,
    exit_code       INT
);

CREATE INDEX IF NOT EXISTS idx_launched_tasks_dockerfile ON launched_tasks(dockerfile_id);
CREATE INDEX IF NOT EXISTS idx_launched_tasks_status ON launched_tasks(status);
