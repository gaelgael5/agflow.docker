-- 115_pitr_basebackup_type.sql
-- Ajoute :
--   * basebackup_type (full | diff | incr) — type des basebackups planifiés
--   * full_rebase_cron — cron du rebase périodique en full (ignoré si type=full)
--
-- Défaut : type='diff', rebase chaque dimanche 02h00 (stratégie validée 2026-05-20).
--          Pour migrer d'un setup full-only, l'utilisateur peut repasser à 'full'
--          dans le PitrConfigDialog.

ALTER TABLE pitr_config
    ADD COLUMN basebackup_type text NOT NULL DEFAULT 'diff'
        CHECK (basebackup_type IN ('full', 'diff', 'incr'));

ALTER TABLE pitr_config
    ADD COLUMN full_rebase_cron text NOT NULL DEFAULT '0 2 * * 0';
