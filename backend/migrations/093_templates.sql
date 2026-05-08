CREATE TABLE IF NOT EXISTS templates (
    slug         VARCHAR(128) NOT NULL PRIMARY KEY,
    display_name TEXT         NOT NULL,
    description  TEXT         NOT NULL DEFAULT '',
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TRIGGER set_updated_at_templates
    BEFORE UPDATE ON templates
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
