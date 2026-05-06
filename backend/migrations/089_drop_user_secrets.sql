-- Supprime l'ancien système de coffre chiffré côté client (PBKDF2 + AES-GCM local)
-- Les secrets utilisateur sont désormais dans Harpocrate sous users/{hash_email}/{name}
DROP TABLE IF EXISTS user_secrets;
ALTER TABLE users
    DROP COLUMN IF EXISTS vault_salt,
    DROP COLUMN IF EXISTS vault_test_ciphertext,
    DROP COLUMN IF EXISTS vault_test_iv;
