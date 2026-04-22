-- Actions génériques attachées à chaque catégorie.
-- Les items (platforms/services) liés à un type de la catégorie rendent
-- dynamiquement une zone de saisie de scripts par action.
--
-- Note : 'platform/create' n'est volontairement PAS seed ici.
-- L'action `create` d'une plateforme a un comportement métier spécial
-- (elle produit des machines) et reste hardcodée dans PlatformDialog.

CREATE TABLE IF NOT EXISTS infra_category_actions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category    VARCHAR NOT NULL REFERENCES infra_categories(name)
                ON UPDATE CASCADE ON DELETE CASCADE,
    name        VARCHAR NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (category, name)
);

INSERT INTO infra_category_actions (category, name) VALUES
    ('platform', 'destroy'),
    ('service',  'install')
ON CONFLICT (category, name) DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_infra_category_actions_category
    ON infra_category_actions(category);
