-- ag.flow — Storage SDK
-- Tables stockage en base (storage_nodes, storage_text, storage_bin)
-- Fonction set_updated_at() déjà définie dans 001_init.sql

CREATE TABLE IF NOT EXISTS storage_nodes (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_id   UUID        REFERENCES storage_nodes(id) ON DELETE CASCADE,
    name        TEXT        NOT NULL,
    mime_type   TEXT,
    kind        SMALLINT    NOT NULL CHECK (kind IN (0, 1, 2)),
    -- 0 = folder | 1 = texte | 2 = binaire
    size        INT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_storage_node UNIQUE (parent_id, name)
);

CREATE TABLE IF NOT EXISTS storage_text (
    node_id     UUID        PRIMARY KEY REFERENCES storage_nodes(id) ON DELETE CASCADE,
    content     TEXT        NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS storage_bin (
    node_id     UUID        PRIMARY KEY REFERENCES storage_nodes(id) ON DELETE CASCADE,
    content     BYTEA       NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Triggers updated_at (set_updated_at() existe déjà depuis 001_init.sql)

CREATE TRIGGER trg_storage_nodes_updated_at
    BEFORE UPDATE ON storage_nodes
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_storage_text_updated_at
    BEFORE UPDATE ON storage_text
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_storage_bin_updated_at
    BEFORE UPDATE ON storage_bin
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- Index navigation (list_folder, write_node_on_disk)
CREATE INDEX IF NOT EXISTS idx_storage_nodes_parent_id
    ON storage_nodes (parent_id);

-- Index filtrage par type
CREATE INDEX IF NOT EXISTS idx_storage_nodes_kind
    ON storage_nodes (kind);

-- Index tri chronologique
CREATE INDEX IF NOT EXISTS idx_storage_nodes_updated_at
    ON storage_nodes (updated_at DESC);
