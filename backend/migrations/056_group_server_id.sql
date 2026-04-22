-- Link groups to target servers for deployment
ALTER TABLE groups ADD COLUMN IF NOT EXISTS server_id UUID REFERENCES infra_servers(id) ON DELETE SET NULL;
