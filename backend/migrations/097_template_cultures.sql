-- Migration 097: table des cultures pour les templates Jinja2
CREATE TABLE template_cultures (
    key        VARCHAR(32) PRIMARY KEY,
    label      TEXT        NOT NULL,
    sort_order INTEGER     NOT NULL DEFAULT 0
);

INSERT INTO template_cultures (key, label, sort_order) VALUES
    ('default', 'Défaut',   0),
    ('en',      'Anglais',  1),
    ('fr',      'Français', 2);
