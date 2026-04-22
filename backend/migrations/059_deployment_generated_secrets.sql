-- Store generated secrets so they persist across regenerations
ALTER TABLE project_deployments ADD COLUMN IF NOT EXISTS generated_secrets JSONB NOT NULL DEFAULT '{}';
