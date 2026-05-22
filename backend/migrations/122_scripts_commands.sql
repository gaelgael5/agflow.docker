-- 122_scripts_commands.sql
-- Liste de commandes nommées attachées à un script.
--
-- Une commande est une paire (name, content) exécutable indépendamment
-- du contexte projet. Dans la majorité des cas il n'y en a qu'une,
-- mais plusieurs variantes peuvent coexister (ex: a, b, c…).

ALTER TABLE scripts
    ADD COLUMN IF NOT EXISTS commands JSONB NOT NULL DEFAULT '[]'::jsonb;
