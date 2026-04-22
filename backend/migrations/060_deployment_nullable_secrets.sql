ALTER TABLE project_deployments ADD COLUMN IF NOT EXISTS nullable_secrets JSONB NOT NULL DEFAULT '[]';
