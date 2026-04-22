-- Relation facultative script ↔ variante typée (infra_named_types).
-- Permet de n'afficher dans l'UI group_scripts que les machines dont le
-- type_id correspond à celui déclaré sur le script.
ALTER TABLE scripts
    ADD COLUMN IF NOT EXISTS execute_on_types_named UUID
    REFERENCES infra_named_types(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_scripts_execute_on_types_named
    ON scripts(execute_on_types_named) WHERE execute_on_types_named IS NOT NULL;
