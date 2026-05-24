-- 124_deploy_wizard.sql
-- Étend project_deployments pour le wizard step-by-step

-- 1. Nouvelles colonnes
ALTER TABLE project_deployments
    ADD COLUMN IF NOT EXISTS current_step_index INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS accumulated_env     JSONB   NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS step_logs           JSONB   NOT NULL DEFAULT '[]';

-- 2. Remplace le CHECK status inline par un CHECK nommé avec tous les états
ALTER TABLE project_deployments
    DROP CONSTRAINT IF EXISTS project_deployments_status_check;

ALTER TABLE project_deployments
    ADD CONSTRAINT project_deployments_status_check
    CHECK (status IN (
        'draft', 'generated',
        'executing_step', 'step_complete', 'step_failed', 'before_complete',
        'deploying', 'deployed', 'failed'
    ));
