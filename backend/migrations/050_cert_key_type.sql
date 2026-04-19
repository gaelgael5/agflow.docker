-- Add key_type column to infra_certificates
ALTER TABLE infra_certificates ADD COLUMN IF NOT EXISTS key_type VARCHAR NOT NULL DEFAULT 'rsa';
