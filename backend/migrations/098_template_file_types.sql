-- Migration 098: table des types de fichiers pour les templates Jinja2
CREATE TABLE template_file_types (
    key        VARCHAR(32) PRIMARY KEY,
    label      TEXT        NOT NULL,
    sort_order INTEGER     NOT NULL DEFAULT 0
);

INSERT INTO template_file_types (key, label, sort_order) VALUES
    ('md', 'Markdown (.md)',   0),
    ('sh', 'Shell (.sh)',      1);
