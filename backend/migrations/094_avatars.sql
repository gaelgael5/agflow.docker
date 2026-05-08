CREATE TABLE IF NOT EXISTS avatar_themes (
    slug         VARCHAR(128) NOT NULL PRIMARY KEY,
    display_name TEXT         NOT NULL,
    description  TEXT         NOT NULL DEFAULT '',
    prompt       TEXT         NOT NULL DEFAULT '',
    provider     TEXT         NOT NULL DEFAULT 'dall-e-3',
    size         TEXT         NOT NULL DEFAULT '1024x1024',
    quality      TEXT         NOT NULL DEFAULT 'hd',
    style        TEXT         NOT NULL DEFAULT 'vivid',
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TRIGGER set_updated_at_avatar_themes
    BEFORE UPDATE ON avatar_themes
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS avatar_characters (
    id             UUID         NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    theme_slug     VARCHAR(128) NOT NULL REFERENCES avatar_themes(slug) ON DELETE CASCADE,
    slug           VARCHAR(128) NOT NULL,
    display_name   TEXT         NOT NULL,
    description    TEXT         NOT NULL DEFAULT '',
    prompt         TEXT         NOT NULL DEFAULT '',
    selected_image INT          DEFAULT NULL,
    created_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    UNIQUE (theme_slug, slug)
);

CREATE TRIGGER set_updated_at_avatar_characters
    BEFORE UPDATE ON avatar_characters
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
