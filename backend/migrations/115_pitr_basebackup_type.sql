-- 115_pitr_basebackup_type.sql
-- Ajoute :
--   * basebackup_type (full | diff | incr) — type des basebackups planifiés
--   * full_rebase_cron — cron du rebase périodique en full (ignoré si type=full)
--
-- Réaligne aussi le default de basebackup_cron sur un intervalle (toutes les 30 minutes)
-- au lieu d'un cron horaire fixe. Le PITR doit pouvoir tourner fréquemment
-- (stratégie validée 2026-05-20 : intervalle + rebase hebdo).

ALTER TABLE pitr_config
    ADD COLUMN basebackup_type text NOT NULL DEFAULT 'diff'
        CHECK (basebackup_type IN ('full', 'diff', 'incr'));

ALTER TABLE pitr_config
    ADD COLUMN full_rebase_cron text NOT NULL DEFAULT '0 2 * * 0';

ALTER TABLE pitr_config
    ALTER COLUMN basebackup_cron SET DEFAULT '*/30 * * * *';

-- Réaligne la valeur seedée par 111 uniquement si elle est encore au default historique
-- (laisse intacte toute personnalisation déjà appliquée).
UPDATE pitr_config
SET basebackup_cron = '*/30 * * * *'
WHERE id = 1 AND basebackup_cron = '0 3 * * *';
