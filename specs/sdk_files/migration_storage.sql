-- ============================================================
-- ag.flow — Storage SDK
-- Migration : migration_storage.sql
-- ============================================================

-- ─── TABLES ─────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS storage_nodes (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_id   UUID        REFERENCES storage_nodes(id) ON DELETE CASCADE,
    name        TEXT        NOT NULL,
    mime_type   TEXT,
    kind        SMALLINT    NOT NULL CHECK (kind IN (0, 1, 2)),
    -- 0 = folder | 1 = text | 2 = binary
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

-- ─── TRIGGER updated_at ─────────────────────────────────────

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_storage_nodes_updated_at
    BEFORE UPDATE ON storage_nodes
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_storage_text_updated_at
    BEFORE UPDATE ON storage_text
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TRIGGER trg_storage_bin_updated_at
    BEFORE UPDATE ON storage_bin
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ─── INDEX ───────────────────────────────────────────────────

-- Navigation : lister les enfants d'un folder
CREATE INDEX IF NOT EXISTS idx_storage_nodes_parent_id
    ON storage_nodes (parent_id);

-- Filtrage par type (folder / text / binary)
CREATE INDEX IF NOT EXISTS idx_storage_nodes_kind
    ON storage_nodes (kind);

-- Tri chronologique (listing récent, audit)
CREATE INDEX IF NOT EXISTS idx_storage_nodes_updated_at
    ON storage_nodes (updated_at DESC);

-- Note : l'index sur (parent_id, name) est couvert par la contrainte UNIQUE
