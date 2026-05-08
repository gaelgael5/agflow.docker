CREATE TABLE IF NOT EXISTS platform_secrets (
    id            UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    key           TEXT        NOT NULL UNIQUE,
    default_value TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TRIGGER set_updated_at_platform_secrets
    BEFORE UPDATE ON platform_secrets
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
