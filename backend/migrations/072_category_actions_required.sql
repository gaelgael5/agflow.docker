-- Flag "required" sur les actions de catégorie.
-- Une machine dont la variante appartient à une catégorie ayant des actions
-- required, et pour lesquelles aucun run ne s'est terminé en succès, est
-- considérée en erreur dans l'UI.
ALTER TABLE infra_category_actions
    ADD COLUMN IF NOT EXISTS is_required BOOLEAN NOT NULL DEFAULT false;
