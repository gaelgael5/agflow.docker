-- 106_harpocrate_vaults_drop_api_key_id.sql — Cleanup colonne descriptive inutilisée
--
-- `api_key_id` a été ajoutée en 105 par analogie avec HARPOCRATE_VAULT_API_KEY_ID
-- (env var remote-backups). En pratique, le SDK Harpocrate utilise uniquement le
-- token API ; cette colonne n'est jamais lue par le code. On la supprime pour
-- ne pas semer la confusion.

ALTER TABLE harpocrate_vaults DROP COLUMN IF EXISTS api_key_id;
