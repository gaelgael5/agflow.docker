-- M8 Infrastructure Registry
-- Tables: types, certificates, servers, machines, machine_metadata

-- ─── Dictionnaire des types ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS infra_types (
    name  VARCHAR PRIMARY KEY,
    type  VARCHAR NOT NULL CHECK (type IN ('platform', 'service'))
);

INSERT INTO infra_types (name, type) VALUES
    ('Proxmox', 'platform'),
    ('LXC',     'service')
ON CONFLICT (name) DO NOTHING;

-- ─── Certificats SSH ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS infra_certificates (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name         VARCHAR NOT NULL,
    private_key  TEXT NOT NULL,
    public_key   TEXT,
    passphrase   VARCHAR,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ─── Servers (hosts SSH-able) ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS infra_servers (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type            VARCHAR NOT NULL REFERENCES infra_types(name),
    host            VARCHAR NOT NULL,
    port            INTEGER NOT NULL DEFAULT 22,
    username        VARCHAR,
    password        VARCHAR,
    certificate_id  UUID REFERENCES infra_certificates(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ─── Machines (ressources K3s-able) ────────────────────────────────
CREATE TABLE IF NOT EXISTS infra_machines (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    host                 VARCHAR NOT NULL,
    port                 INTEGER NOT NULL DEFAULT 22,
    type                 VARCHAR NOT NULL REFERENCES infra_types(name),
    server_id            UUID REFERENCES infra_servers(id) ON DELETE SET NULL,
    username             VARCHAR,
    password             VARCHAR,
    certificate_id       UUID REFERENCES infra_certificates(id) ON DELETE SET NULL,
    install_status       VARCHAR NOT NULL DEFAULT 'pending'
                         CHECK (install_status IN ('pending', 'initializing', 'installed', 'failed')),
    install_step         INTEGER NOT NULL DEFAULT 0,
    install_total        INTEGER,
    install_started_at   TIMESTAMPTZ,
    install_finished_at  TIMESTAMPTZ,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ─── Metadata post-install ─────────────────────────────────────────
CREATE TABLE IF NOT EXISTS infra_machine_metadata (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    machine_id   UUID NOT NULL REFERENCES infra_machines(id) ON DELETE CASCADE,
    key          VARCHAR NOT NULL,
    value        TEXT NOT NULL,
    is_sensitive BOOLEAN NOT NULL DEFAULT false,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (machine_id, key)
);

-- ─── Trigger updated_at ───────────────────────────────────────────
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_infra_certificates_updated_at') THEN
        CREATE TRIGGER trg_infra_certificates_updated_at BEFORE UPDATE ON infra_certificates FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_infra_servers_updated_at') THEN
        CREATE TRIGGER trg_infra_servers_updated_at BEFORE UPDATE ON infra_servers FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_infra_machines_updated_at') THEN
        CREATE TRIGGER trg_infra_machines_updated_at BEFORE UPDATE ON infra_machines FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_infra_machine_metadata_updated_at') THEN
        CREATE TRIGGER trg_infra_machine_metadata_updated_at BEFORE UPDATE ON infra_machine_metadata FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
END $$;

-- ─── Index ────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_infra_machines_server_id ON infra_machines(server_id) WHERE server_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_infra_machines_install_status ON infra_machines(install_status);
CREATE INDEX IF NOT EXISTS idx_infra_servers_certificate_id ON infra_servers(certificate_id) WHERE certificate_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_infra_machines_certificate_id ON infra_machines(certificate_id) WHERE certificate_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_infra_machine_metadata_machine_id ON infra_machine_metadata(machine_id);
