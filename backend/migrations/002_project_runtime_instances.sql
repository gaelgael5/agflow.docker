-- 002_project_runtime_instances.sql
--
-- Matérialisation des resources par-(runtime × instance) pour le contrat
-- workflow v5 §3.4. Le `id` de cette table devient le `resource_id` exposé
-- à ag.flow, stable par runtime et CASCADE avec lui.
--
-- Symétrique à project_group_runtimes (pivot N-N) mais à la granularité
-- instance individuelle. mcp_bindings ne sont pas dupliqués : ils restent
-- sur le template `instances` et sont lus via JOIN au moment du GET /resources.

CREATE TABLE project_runtime_instances (
    id uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
    project_runtime_id uuid NOT NULL REFERENCES project_runtimes(id) ON DELETE CASCADE,
    instance_id uuid NOT NULL REFERENCES instances(id) ON DELETE RESTRICT,
    connection_params jsonb,
    setup_steps jsonb DEFAULT '[]'::jsonb NOT NULL,
    provisioning_status varchar(32) NOT NULL DEFAULT 'provisioning',
    container_id text,
    service_url varchar,
    error_message text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT project_runtime_instances_status_check
        CHECK (provisioning_status IN ('provisioning','ready','pending_setup','failed')),
    UNIQUE (project_runtime_id, instance_id)
);

CREATE INDEX idx_pri_runtime ON project_runtime_instances(project_runtime_id);
CREATE INDEX idx_pri_status ON project_runtime_instances(provisioning_status);

CREATE TRIGGER set_updated_at_project_runtime_instances
    BEFORE UPDATE ON project_runtime_instances
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
