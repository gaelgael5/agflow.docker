-- 026_user_vault.sql
ALTER TABLE users ADD COLUMN IF NOT EXISTS vault_salt TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS vault_test_ciphertext TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS vault_test_iv TEXT;
