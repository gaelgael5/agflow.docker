-- 001_init.sql — schéma consolidé agflow.docker
--
-- Ce fichier remplace 86 migrations historiques (versions 001 à 086) par une
-- seule représentation finale du schéma. Les environnements existants (qui
-- ont déjà appliqué les migrations 001-086) ne sont pas affectés car le
-- runner skippe toute version déjà présente dans schema_migrations.
--
-- Pour ajouter de nouvelles migrations : créer 002_<descr>.sql, 003_… etc.

-- pgcrypto (EXTENSION)

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;

-- uuid-ossp (EXTENSION)

CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA public;

-- set_updated_at() (FUNCTION)

CREATE FUNCTION set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

-- agent_api_contracts (TABLE)

CREATE TABLE agent_api_contracts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    agent_id text NOT NULL,
    slug text NOT NULL,
    display_name text NOT NULL,
    description text DEFAULT ''::text NOT NULL,
    source_type text DEFAULT 'manual'::text NOT NULL,
    source_url text,
    spec_content text NOT NULL,
    base_url text DEFAULT ''::text NOT NULL,
    auth_header text DEFAULT 'Authorization'::text NOT NULL,
    auth_prefix text DEFAULT 'Bearer'::text NOT NULL,
    auth_secret_ref text,
    parsed_tags jsonb DEFAULT '[]'::jsonb NOT NULL,
    "position" integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    output_dir text DEFAULT 'workspace/docs/ctr'::text NOT NULL,
    tag_overrides jsonb DEFAULT '{}'::jsonb NOT NULL,
    managed_by_instance uuid,
    runtime_base_url text DEFAULT ''::text NOT NULL,
    CONSTRAINT agent_api_contracts_source_type_check CHECK ((source_type = ANY (ARRAY['upload'::text, 'url'::text, 'manual'::text])))
);

-- agent_message_delivery (TABLE)

CREATE TABLE agent_message_delivery (
    group_name text NOT NULL,
    msg_id uuid NOT NULL,
    status text NOT NULL,
    claimed_at timestamp with time zone,
    claimed_by text,
    acked_at timestamp with time zone,
    retry_count integer DEFAULT 0 NOT NULL,
    last_error text,
    CONSTRAINT agent_message_delivery_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'claimed'::text, 'acked'::text, 'failed'::text])))
);

-- agent_messages (TABLE)

CREATE TABLE agent_messages (
    msg_id uuid DEFAULT gen_random_uuid() NOT NULL,
    parent_msg_id uuid,
    v integer DEFAULT 1 NOT NULL,
    session_id text NOT NULL,
    instance_id text NOT NULL,
    direction text NOT NULL,
    kind text NOT NULL,
    payload jsonb NOT NULL,
    route jsonb,
    source text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT agent_messages_direction_check CHECK ((direction = ANY (ARRAY['in'::text, 'out'::text]))),
    CONSTRAINT agent_messages_kind_check CHECK ((kind = ANY (ARRAY['instruction'::text, 'cancel'::text, 'event'::text, 'result'::text, 'error'::text])))
);

-- agents_catalog (TABLE)

CREATE TABLE agents_catalog (
    slug text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    last_seen timestamp with time zone DEFAULT now() NOT NULL
);

-- agents_instances (TABLE)

CREATE TABLE agents_instances (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    session_id uuid NOT NULL,
    agent_id text NOT NULL,
    labels jsonb DEFAULT '{}'::jsonb NOT NULL,
    mission text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    destroyed_at timestamp with time zone,
    last_container_name text,
    last_activity_at timestamp with time zone DEFAULT now() NOT NULL,
    status text DEFAULT 'idle'::text NOT NULL,
    error_message text,
    mcp_bindings_injected jsonb DEFAULT '[]'::jsonb NOT NULL,
    CONSTRAINT agents_instances_status_chk CHECK ((status = ANY (ARRAY['idle'::text, 'busy'::text, 'error'::text, 'destroyed'::text])))
);

-- api_keys (TABLE)

CREATE TABLE api_keys (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    owner_id uuid,
    name text NOT NULL,
    prefix text NOT NULL,
    key_hash text NOT NULL,
    scopes text[] DEFAULT '{}'::text[] NOT NULL,
    rate_limit integer DEFAULT 120 NOT NULL,
    expires_at timestamp with time zone,
    revoked boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    last_used_at timestamp with time zone
);

-- deployment_instances (TABLE)

CREATE TABLE deployment_instances (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    deployment_id uuid NOT NULL,
    instance_id uuid NOT NULL,
    machine_id uuid,
    deployed_at timestamp with time zone DEFAULT now() NOT NULL,
    success boolean,
    error_message text
);

-- discovery_services (TABLE)

CREATE TABLE discovery_services (
    id text NOT NULL,
    name text NOT NULL,
    base_url text NOT NULL,
    api_key_var text,
    description text DEFAULT ''::text NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

-- dockerfile_builds (TABLE)

CREATE TABLE dockerfile_builds (
    id uuid DEFAULT uuid_generate_v4() NOT NULL,
    dockerfile_id text NOT NULL,
    content_hash text NOT NULL,
    image_tag text NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    logs text DEFAULT ''::text NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    CONSTRAINT dockerfile_builds_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'running'::text, 'success'::text, 'failed'::text])))
);

-- dockerfiles (TABLE)

CREATE TABLE dockerfiles (
    id text NOT NULL,
    display_name text NOT NULL,
    description text DEFAULT ''::text NOT NULL,
    parameters jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

-- group_scripts (TABLE)

CREATE TABLE group_scripts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    group_id uuid NOT NULL,
    script_id uuid NOT NULL,
    machine_id uuid NOT NULL,
    timing character varying NOT NULL,
    "position" integer DEFAULT 0 NOT NULL,
    env_mapping jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    input_values jsonb DEFAULT '{}'::jsonb NOT NULL,
    trigger_rules jsonb DEFAULT '[]'::jsonb NOT NULL,
    input_statuses jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT group_scripts_timing_check CHECK (((timing)::text = ANY ((ARRAY['before'::character varying, 'after'::character varying])::text[])))
);

-- groups (TABLE)

CREATE TABLE groups (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id uuid NOT NULL,
    name character varying(200) NOT NULL,
    max_agents integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    machine_id uuid,
    compose_template_slug character varying,
    max_replicas integer DEFAULT 1 NOT NULL,
    CONSTRAINT groups_max_replicas_check CHECK ((max_replicas >= 1))
);

-- hmac_keys (TABLE)

CREATE TABLE hmac_keys (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    key_id character varying(64) NOT NULL,
    key_value_encrypted bytea NOT NULL,
    description text DEFAULT ''::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    rotated_at timestamp with time zone
);

-- infra_categories (TABLE)

CREATE TABLE infra_categories (
    name character varying NOT NULL,
    is_vps boolean DEFAULT false NOT NULL
);

-- infra_category_actions (TABLE)

CREATE TABLE infra_category_actions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    category character varying NOT NULL,
    name character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    is_required boolean DEFAULT false NOT NULL
);

-- infra_certificates (TABLE)

CREATE TABLE infra_certificates (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying NOT NULL,
    private_key text NOT NULL,
    public_key text,
    passphrase character varying,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    key_type character varying DEFAULT 'rsa'::character varying NOT NULL
);

-- infra_machines (TABLE)

CREATE TABLE infra_machines (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    host character varying NOT NULL,
    port integer DEFAULT 22 NOT NULL,
    username character varying,
    password character varying,
    certificate_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    name character varying DEFAULT ''::character varying NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    status character varying DEFAULT 'not_initialized'::character varying NOT NULL,
    parent_id uuid,
    type_id uuid NOT NULL,
    user_id uuid,
    environment character varying(50)
);

-- infra_machines_runs (TABLE)

CREATE TABLE infra_machines_runs (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    machine_id uuid NOT NULL,
    action_id uuid NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    success boolean,
    exit_code integer,
    error_message text,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

-- infra_named_type_actions (TABLE)

CREATE TABLE infra_named_type_actions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    named_type_id uuid NOT NULL,
    category_action_id uuid NOT NULL,
    url character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

-- infra_named_types (TABLE)

CREATE TABLE infra_named_types (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    connection_type character varying NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    name character varying DEFAULT ''::character varying NOT NULL,
    type_id character varying NOT NULL,
    sub_type_id uuid
);

-- instances (TABLE)

CREATE TABLE instances (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    group_id uuid NOT NULL,
    instance_name character varying(128) NOT NULL,
    catalog_id character varying(128) NOT NULL,
    variables jsonb DEFAULT '{}'::jsonb NOT NULL,
    status character varying(20) DEFAULT 'draft'::character varying NOT NULL,
    service_url character varying,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    variable_statuses jsonb DEFAULT '{}'::jsonb NOT NULL,
    connection_params jsonb,
    mcp_bindings jsonb DEFAULT '[]'::jsonb NOT NULL,
    setup_steps jsonb DEFAULT '[]'::jsonb NOT NULL,
    provisioning_status character varying(32) DEFAULT 'ready'::character varying NOT NULL,
    CONSTRAINT instances_provisioning_status_check CHECK (((provisioning_status)::text = ANY ((ARRAY['provisioning'::character varying, 'ready'::character varying, 'pending_setup'::character varying, 'failed'::character varying])::text[]))),
    CONSTRAINT instances_status_check CHECK (((status)::text = ANY ((ARRAY['draft'::character varying, 'active'::character varying, 'stopped'::character varying])::text[])))
);

-- launched_tasks (TABLE)

CREATE TABLE launched_tasks (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    dockerfile_id text NOT NULL,
    container_id text,
    container_name text,
    instruction text DEFAULT ''::text NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    started_at timestamp with time zone DEFAULT now() NOT NULL,
    finished_at timestamp with time zone,
    exit_code integer,
    CONSTRAINT launched_tasks_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'running'::text, 'success'::text, 'failure'::text, 'stopped'::text, 'error'::text])))
);

-- mcp_servers (TABLE)

CREATE TABLE mcp_servers (
    id uuid DEFAULT uuid_generate_v4() NOT NULL,
    discovery_service_id text NOT NULL,
    package_id text NOT NULL,
    name text NOT NULL,
    repo text DEFAULT ''::text NOT NULL,
    repo_url text DEFAULT ''::text NOT NULL,
    transport text DEFAULT 'stdio'::text NOT NULL,
    short_description text DEFAULT ''::text NOT NULL,
    long_description text DEFAULT ''::text NOT NULL,
    documentation_url text DEFAULT ''::text NOT NULL,
    parameters jsonb DEFAULT '{}'::jsonb NOT NULL,
    parameters_schema jsonb DEFAULT '[]'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    recipes jsonb DEFAULT '{}'::jsonb NOT NULL,
    category text DEFAULT ''::text NOT NULL,
    CONSTRAINT mcp_servers_transport_check CHECK ((transport = ANY (ARRAY['stdio'::text, 'sse'::text, 'docker'::text])))
);

-- outbound_hooks (TABLE)

CREATE TABLE outbound_hooks (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    hook_id uuid NOT NULL,
    task_id uuid,
    callback_url text NOT NULL,
    hmac_key_id character varying(64) NOT NULL,
    payload jsonb NOT NULL,
    attempt_number integer DEFAULT 0 NOT NULL,
    status character varying(32) DEFAULT 'pending'::character varying NOT NULL,
    last_response_code integer,
    last_attempt_at timestamp with time zone,
    next_retry_at timestamp with time zone DEFAULT now() NOT NULL,
    error_message text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT outbound_hooks_status_check CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'delivered'::character varying, 'dead'::character varying])::text[])))
);

-- platform_config (TABLE)

CREATE TABLE platform_config (
    key text NOT NULL,
    value text NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

-- project_deployments (TABLE)

CREATE TABLE project_deployments (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id uuid NOT NULL,
    user_id uuid NOT NULL,
    group_servers jsonb DEFAULT '{}'::jsonb NOT NULL,
    status character varying(20) DEFAULT 'draft'::character varying NOT NULL,
    generated_compose text,
    generated_env text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    generated_secrets jsonb DEFAULT '{}'::jsonb NOT NULL,
    nullable_secrets jsonb DEFAULT '[]'::jsonb NOT NULL,
    generated_data jsonb DEFAULT '{}'::jsonb NOT NULL,
    CONSTRAINT project_deployments_status_check CHECK (((status)::text = ANY ((ARRAY['draft'::character varying, 'generated'::character varying, 'deployed'::character varying])::text[])))
);

-- project_group_runtimes (TABLE)

CREATE TABLE project_group_runtimes (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_runtime_id uuid NOT NULL,
    group_id uuid NOT NULL,
    machine_id uuid,
    env_text text DEFAULT ''::text NOT NULL,
    compose_yaml text DEFAULT ''::text NOT NULL,
    remote_path text DEFAULT ''::text NOT NULL,
    status character varying DEFAULT 'pending'::character varying NOT NULL,
    pushed_at timestamp with time zone,
    error_message text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    seq bigint NOT NULL,
    deleted_at timestamp with time zone,
    replica_count integer DEFAULT 1 NOT NULL,
    CONSTRAINT project_group_runtimes_replica_count_check CHECK ((replica_count >= 0)),
    CONSTRAINT project_group_runtimes_status_check CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'deployed'::character varying, 'failed'::character varying])::text[])))
);

-- project_group_runtimes_seq_seq (SEQUENCE)

ALTER TABLE project_group_runtimes ALTER COLUMN seq ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME project_group_runtimes_seq_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

-- project_runtimes (TABLE)

CREATE TABLE project_runtimes (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    project_id uuid NOT NULL,
    deployment_id uuid,
    user_id uuid,
    status character varying DEFAULT 'pending'::character varying NOT NULL,
    pushed_at timestamp with time zone,
    error_message text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    seq bigint NOT NULL,
    deleted_at timestamp with time zone,
    CONSTRAINT project_runtimes_status_check CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'deployed'::character varying, 'failed'::character varying])::text[])))
);

-- project_runtimes_seq_seq (SEQUENCE)

ALTER TABLE project_runtimes ALTER COLUMN seq ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME project_runtimes_seq_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

-- projects (TABLE)

CREATE TABLE projects (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    display_name character varying(200) NOT NULL,
    description text DEFAULT ''::text NOT NULL,
    tags jsonb DEFAULT '[]'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    network character varying DEFAULT 'agflow'::character varying NOT NULL
);

-- rate_limit_counters (TABLE)

CREATE TABLE rate_limit_counters (
    key text NOT NULL,
    window_start timestamp with time zone DEFAULT date_trunc('minute'::text, now()) NOT NULL,
    count integer DEFAULT 1 NOT NULL
);

-- role_sections (TABLE)

CREATE TABLE role_sections (
    role_id text NOT NULL,
    name text NOT NULL,
    display_name text NOT NULL,
    is_native boolean DEFAULT false NOT NULL,
    "position" integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

-- roles (TABLE)

CREATE TABLE roles (
    id text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

-- scripts (TABLE)

CREATE TABLE scripts (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    name character varying NOT NULL,
    description text DEFAULT ''::text NOT NULL,
    content text DEFAULT ''::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    execute_on_types_named uuid,
    input_variables jsonb DEFAULT '[]'::jsonb NOT NULL
);

-- secrets (TABLE)

CREATE TABLE secrets (
    id uuid DEFAULT uuid_generate_v4() NOT NULL,
    var_name text NOT NULL,
    value_encrypted bytea NOT NULL,
    scope text DEFAULT 'global'::text NOT NULL,
    agent_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT secrets_scope_check CHECK ((scope = ANY (ARRAY['global'::text, 'agent'::text])))
);

-- service_types (TABLE)

CREATE TABLE service_types (
    name text NOT NULL,
    display_name text NOT NULL,
    is_native boolean DEFAULT false NOT NULL,
    "position" integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

-- sessions (TABLE)

CREATE TABLE sessions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    api_key_id uuid NOT NULL,
    name text,
    status text DEFAULT 'active'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    closed_at timestamp with time zone,
    project_id text,
    project_runtime_id uuid,
    callback_url text,
    callback_hmac_key_id character varying(64),
    CONSTRAINT sessions_status_check CHECK ((status = ANY (ARRAY['active'::text, 'closed'::text, 'expired'::text])))
);

-- skills (TABLE)

CREATE TABLE skills (
    id uuid DEFAULT uuid_generate_v4() NOT NULL,
    discovery_service_id text NOT NULL,
    skill_id text NOT NULL,
    name text NOT NULL,
    description text DEFAULT ''::text NOT NULL,
    content_md text DEFAULT ''::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

-- tasks (TABLE)

CREATE TABLE tasks (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    kind character varying(64) NOT NULL,
    project_runtime_id uuid,
    session_id uuid,
    agent_instance_id uuid,
    status character varying(32) DEFAULT 'pending'::character varying NOT NULL,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    result jsonb,
    error jsonb,
    agflow_action_execution_id uuid,
    agflow_correlation_id uuid,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT tasks_kind_check CHECK (((kind)::text = ANY ((ARRAY['runtime_provision'::character varying, 'session_create'::character varying, 'agent_create'::character varying, 'session_work'::character varying])::text[]))),
    CONSTRAINT tasks_status_check CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'running'::character varying, 'completed'::character varying, 'failed'::character varying, 'cancelled'::character varying])::text[])))
);

-- user_identities (TABLE)

CREATE TABLE user_identities (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    provider text NOT NULL,
    subject text NOT NULL,
    email text,
    raw_claims jsonb,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);

-- user_secrets (TABLE)

CREATE TABLE user_secrets (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    name text NOT NULL,
    ciphertext text NOT NULL,
    iv text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);

-- users (TABLE)

CREATE TABLE users (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    email text NOT NULL,
    name text DEFAULT ''::text NOT NULL,
    avatar_url text DEFAULT ''::text NOT NULL,
    role text DEFAULT 'user'::text NOT NULL,
    scopes text[] DEFAULT '{}'::text[] NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    approved_at timestamp with time zone,
    approved_by uuid,
    last_login timestamp with time zone,
    vault_salt text,
    vault_test_ciphertext text,
    vault_test_iv text,
    CONSTRAINT users_role_check CHECK ((role = ANY (ARRAY['admin'::text, 'user'::text]))),
    CONSTRAINT users_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'active'::text, 'disabled'::text])))
);

-- agent_api_contracts agent_api_contracts_agent_id_slug_key (CONSTRAINT)

ALTER TABLE ONLY agent_api_contracts
    ADD CONSTRAINT agent_api_contracts_agent_id_slug_key UNIQUE (agent_id, slug);

-- agent_api_contracts agent_api_contracts_pkey (CONSTRAINT)

ALTER TABLE ONLY agent_api_contracts
    ADD CONSTRAINT agent_api_contracts_pkey PRIMARY KEY (id);

-- agent_message_delivery agent_message_delivery_pkey (CONSTRAINT)

ALTER TABLE ONLY agent_message_delivery
    ADD CONSTRAINT agent_message_delivery_pkey PRIMARY KEY (group_name, msg_id);

-- agent_messages agent_messages_pkey (CONSTRAINT)

ALTER TABLE ONLY agent_messages
    ADD CONSTRAINT agent_messages_pkey PRIMARY KEY (msg_id);

-- agents_catalog agents_catalog_pkey (CONSTRAINT)

ALTER TABLE ONLY agents_catalog
    ADD CONSTRAINT agents_catalog_pkey PRIMARY KEY (slug);

-- agents_instances agents_instances_pkey (CONSTRAINT)

ALTER TABLE ONLY agents_instances
    ADD CONSTRAINT agents_instances_pkey PRIMARY KEY (id);

-- api_keys api_keys_pkey (CONSTRAINT)

ALTER TABLE ONLY api_keys
    ADD CONSTRAINT api_keys_pkey PRIMARY KEY (id);

-- api_keys api_keys_prefix_key (CONSTRAINT)

ALTER TABLE ONLY api_keys
    ADD CONSTRAINT api_keys_prefix_key UNIQUE (prefix);

-- deployment_instances deployment_instances_pkey (CONSTRAINT)

ALTER TABLE ONLY deployment_instances
    ADD CONSTRAINT deployment_instances_pkey PRIMARY KEY (id);

-- discovery_services discovery_services_pkey (CONSTRAINT)

ALTER TABLE ONLY discovery_services
    ADD CONSTRAINT discovery_services_pkey PRIMARY KEY (id);

-- dockerfile_builds dockerfile_builds_pkey (CONSTRAINT)

ALTER TABLE ONLY dockerfile_builds
    ADD CONSTRAINT dockerfile_builds_pkey PRIMARY KEY (id);

-- dockerfiles dockerfiles_pkey (CONSTRAINT)

ALTER TABLE ONLY dockerfiles
    ADD CONSTRAINT dockerfiles_pkey PRIMARY KEY (id);

-- group_scripts group_scripts_pkey (CONSTRAINT)

ALTER TABLE ONLY group_scripts
    ADD CONSTRAINT group_scripts_pkey PRIMARY KEY (id);

-- groups groups_pkey (CONSTRAINT)

ALTER TABLE ONLY groups
    ADD CONSTRAINT groups_pkey PRIMARY KEY (id);

-- groups groups_project_id_name_key (CONSTRAINT)

ALTER TABLE ONLY groups
    ADD CONSTRAINT groups_project_id_name_key UNIQUE (project_id, name);

-- hmac_keys hmac_keys_key_id_key (CONSTRAINT)

ALTER TABLE ONLY hmac_keys
    ADD CONSTRAINT hmac_keys_key_id_key UNIQUE (key_id);

-- hmac_keys hmac_keys_pkey (CONSTRAINT)

ALTER TABLE ONLY hmac_keys
    ADD CONSTRAINT hmac_keys_pkey PRIMARY KEY (id);

-- infra_categories infra_categories_pkey (CONSTRAINT)

ALTER TABLE ONLY infra_categories
    ADD CONSTRAINT infra_categories_pkey PRIMARY KEY (name);

-- infra_category_actions infra_category_actions_category_name_key (CONSTRAINT)

ALTER TABLE ONLY infra_category_actions
    ADD CONSTRAINT infra_category_actions_category_name_key UNIQUE (category, name);

-- infra_category_actions infra_category_actions_pkey (CONSTRAINT)

ALTER TABLE ONLY infra_category_actions
    ADD CONSTRAINT infra_category_actions_pkey PRIMARY KEY (id);

-- infra_certificates infra_certificates_pkey (CONSTRAINT)

ALTER TABLE ONLY infra_certificates
    ADD CONSTRAINT infra_certificates_pkey PRIMARY KEY (id);

-- infra_machines_runs infra_machines_runs_pkey (CONSTRAINT)

ALTER TABLE ONLY infra_machines_runs
    ADD CONSTRAINT infra_machines_runs_pkey PRIMARY KEY (id);

-- infra_named_type_actions infra_named_type_actions_named_type_id_category_action_id_key (CONSTRAINT)

ALTER TABLE ONLY infra_named_type_actions
    ADD CONSTRAINT infra_named_type_actions_named_type_id_category_action_id_key UNIQUE (named_type_id, category_action_id);

-- infra_named_type_actions infra_named_type_actions_pkey (CONSTRAINT)

ALTER TABLE ONLY infra_named_type_actions
    ADD CONSTRAINT infra_named_type_actions_pkey PRIMARY KEY (id);

-- infra_named_types infra_named_types_pkey (CONSTRAINT)

ALTER TABLE ONLY infra_named_types
    ADD CONSTRAINT infra_named_types_pkey PRIMARY KEY (id);

-- infra_machines infra_servers_pkey (CONSTRAINT)

ALTER TABLE ONLY infra_machines
    ADD CONSTRAINT infra_servers_pkey PRIMARY KEY (id);

-- instances instances_group_id_instance_name_key (CONSTRAINT)

ALTER TABLE ONLY instances
    ADD CONSTRAINT instances_group_id_instance_name_key UNIQUE (group_id, instance_name);

-- instances instances_pkey (CONSTRAINT)

ALTER TABLE ONLY instances
    ADD CONSTRAINT instances_pkey PRIMARY KEY (id);

-- launched_tasks launched_tasks_pkey (CONSTRAINT)

ALTER TABLE ONLY launched_tasks
    ADD CONSTRAINT launched_tasks_pkey PRIMARY KEY (id);

-- mcp_servers mcp_servers_discovery_service_id_package_id_key (CONSTRAINT)

ALTER TABLE ONLY mcp_servers
    ADD CONSTRAINT mcp_servers_discovery_service_id_package_id_key UNIQUE (discovery_service_id, package_id);

-- mcp_servers mcp_servers_pkey (CONSTRAINT)

ALTER TABLE ONLY mcp_servers
    ADD CONSTRAINT mcp_servers_pkey PRIMARY KEY (id);

-- outbound_hooks outbound_hooks_hook_id_key (CONSTRAINT)

ALTER TABLE ONLY outbound_hooks
    ADD CONSTRAINT outbound_hooks_hook_id_key UNIQUE (hook_id);

-- outbound_hooks outbound_hooks_pkey (CONSTRAINT)

ALTER TABLE ONLY outbound_hooks
    ADD CONSTRAINT outbound_hooks_pkey PRIMARY KEY (id);

-- platform_config platform_config_pkey (CONSTRAINT)

ALTER TABLE ONLY platform_config
    ADD CONSTRAINT platform_config_pkey PRIMARY KEY (key);

-- project_deployments project_deployments_pkey (CONSTRAINT)

ALTER TABLE ONLY project_deployments
    ADD CONSTRAINT project_deployments_pkey PRIMARY KEY (id);

-- project_group_runtimes project_group_runtimes_pkey (CONSTRAINT)

ALTER TABLE ONLY project_group_runtimes
    ADD CONSTRAINT project_group_runtimes_pkey PRIMARY KEY (id);

-- project_group_runtimes project_group_runtimes_project_runtime_id_group_id_key (CONSTRAINT)

ALTER TABLE ONLY project_group_runtimes
    ADD CONSTRAINT project_group_runtimes_project_runtime_id_group_id_key UNIQUE (project_runtime_id, group_id);

-- project_group_runtimes project_group_runtimes_seq_key (CONSTRAINT)

ALTER TABLE ONLY project_group_runtimes
    ADD CONSTRAINT project_group_runtimes_seq_key UNIQUE (seq);

-- project_runtimes project_runtimes_pkey (CONSTRAINT)

ALTER TABLE ONLY project_runtimes
    ADD CONSTRAINT project_runtimes_pkey PRIMARY KEY (id);

-- project_runtimes project_runtimes_seq_key (CONSTRAINT)

ALTER TABLE ONLY project_runtimes
    ADD CONSTRAINT project_runtimes_seq_key UNIQUE (seq);

-- projects projects_pkey (CONSTRAINT)

ALTER TABLE ONLY projects
    ADD CONSTRAINT projects_pkey PRIMARY KEY (id);

-- rate_limit_counters rate_limit_counters_pkey (CONSTRAINT)

ALTER TABLE ONLY rate_limit_counters
    ADD CONSTRAINT rate_limit_counters_pkey PRIMARY KEY (key, window_start);

-- role_sections role_sections_pkey (CONSTRAINT)

ALTER TABLE ONLY role_sections
    ADD CONSTRAINT role_sections_pkey PRIMARY KEY (role_id, name);

-- roles roles_pkey (CONSTRAINT)

ALTER TABLE ONLY roles
    ADD CONSTRAINT roles_pkey PRIMARY KEY (id);

-- scripts scripts_name_key (CONSTRAINT)

ALTER TABLE ONLY scripts
    ADD CONSTRAINT scripts_name_key UNIQUE (name);

-- scripts scripts_pkey (CONSTRAINT)

ALTER TABLE ONLY scripts
    ADD CONSTRAINT scripts_pkey PRIMARY KEY (id);

-- secrets secrets_pkey (CONSTRAINT)

ALTER TABLE ONLY secrets
    ADD CONSTRAINT secrets_pkey PRIMARY KEY (id);

-- secrets secrets_var_name_scope_agent_id_key (CONSTRAINT)

ALTER TABLE ONLY secrets
    ADD CONSTRAINT secrets_var_name_scope_agent_id_key UNIQUE NULLS NOT DISTINCT (var_name, scope, agent_id);

-- service_types service_types_pkey (CONSTRAINT)

ALTER TABLE ONLY service_types
    ADD CONSTRAINT service_types_pkey PRIMARY KEY (name);

-- sessions sessions_pkey (CONSTRAINT)

ALTER TABLE ONLY sessions
    ADD CONSTRAINT sessions_pkey PRIMARY KEY (id);

-- skills skills_discovery_service_id_skill_id_key (CONSTRAINT)

ALTER TABLE ONLY skills
    ADD CONSTRAINT skills_discovery_service_id_skill_id_key UNIQUE (discovery_service_id, skill_id);

-- skills skills_pkey (CONSTRAINT)

ALTER TABLE ONLY skills
    ADD CONSTRAINT skills_pkey PRIMARY KEY (id);

-- tasks tasks_pkey (CONSTRAINT)

ALTER TABLE ONLY tasks
    ADD CONSTRAINT tasks_pkey PRIMARY KEY (id);

-- user_identities user_identities_pkey (CONSTRAINT)

ALTER TABLE ONLY user_identities
    ADD CONSTRAINT user_identities_pkey PRIMARY KEY (id);

-- user_identities user_identities_provider_subject_key (CONSTRAINT)

ALTER TABLE ONLY user_identities
    ADD CONSTRAINT user_identities_provider_subject_key UNIQUE (provider, subject);

-- user_secrets user_secrets_pkey (CONSTRAINT)

ALTER TABLE ONLY user_secrets
    ADD CONSTRAINT user_secrets_pkey PRIMARY KEY (id);

-- user_secrets user_secrets_user_id_name_key (CONSTRAINT)

ALTER TABLE ONLY user_secrets
    ADD CONSTRAINT user_secrets_user_id_name_key UNIQUE (user_id, name);

-- users users_email_key (CONSTRAINT)

ALTER TABLE ONLY users
    ADD CONSTRAINT users_email_key UNIQUE (email);

-- users users_pkey (CONSTRAINT)

ALTER TABLE ONLY users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);

-- idx_agent_api_contracts_agent (INDEX)

CREATE INDEX idx_agent_api_contracts_agent ON agent_api_contracts USING btree (agent_id, "position");

-- idx_agent_messages_instance_dir_ts (INDEX)

CREATE INDEX idx_agent_messages_instance_dir_ts ON agent_messages USING btree (instance_id, direction, created_at);

-- idx_agent_messages_parent (INDEX)

CREATE INDEX idx_agent_messages_parent ON agent_messages USING btree (parent_msg_id) WHERE (parent_msg_id IS NOT NULL);

-- idx_agent_messages_session_ts (INDEX)

CREATE INDEX idx_agent_messages_session_ts ON agent_messages USING btree (session_id, created_at);

-- idx_agents_instances_last_container (INDEX)

CREATE INDEX idx_agents_instances_last_container ON agents_instances USING btree (last_container_name) WHERE (last_container_name IS NOT NULL);

-- idx_agents_instances_session (INDEX)

CREATE INDEX idx_agents_instances_session ON agents_instances USING btree (session_id) WHERE (destroyed_at IS NULL);

-- idx_agents_instances_status_activity (INDEX)

CREATE INDEX idx_agents_instances_status_activity ON agents_instances USING btree (status, last_activity_at) WHERE (destroyed_at IS NULL);

-- idx_api_keys_owner (INDEX)

CREATE INDEX idx_api_keys_owner ON api_keys USING btree (owner_id);

-- idx_api_keys_prefix (INDEX)

CREATE INDEX idx_api_keys_prefix ON api_keys USING btree (prefix);

-- idx_delivery_group_pending (INDEX)

CREATE INDEX idx_delivery_group_pending ON agent_message_delivery USING btree (group_name, status, msg_id) WHERE (status = ANY (ARRAY['pending'::text, 'claimed'::text]));

-- idx_deployment_instances_deployment (INDEX)

CREATE INDEX idx_deployment_instances_deployment ON deployment_instances USING btree (deployment_id);

-- idx_deployment_instances_instance_recent (INDEX)

CREATE INDEX idx_deployment_instances_instance_recent ON deployment_instances USING btree (instance_id, deployed_at DESC);

-- idx_deployment_instances_machine (INDEX)

CREATE INDEX idx_deployment_instances_machine ON deployment_instances USING btree (machine_id) WHERE (machine_id IS NOT NULL);

-- idx_dockerfile_builds_dockerfile (INDEX)

CREATE INDEX idx_dockerfile_builds_dockerfile ON dockerfile_builds USING btree (dockerfile_id, started_at DESC);

-- idx_dockerfiles_display_name (INDEX)

CREATE INDEX idx_dockerfiles_display_name ON dockerfiles USING btree (display_name);

-- idx_group_scripts_group_timing (INDEX)

CREATE INDEX idx_group_scripts_group_timing ON group_scripts USING btree (group_id, timing, "position");

-- idx_group_scripts_machine_id (INDEX)

CREATE INDEX idx_group_scripts_machine_id ON group_scripts USING btree (machine_id);

-- idx_group_scripts_script_id (INDEX)

CREATE INDEX idx_group_scripts_script_id ON group_scripts USING btree (script_id);

-- idx_groups_project_id (INDEX)

CREATE INDEX idx_groups_project_id ON groups USING btree (project_id);

-- idx_infra_category_actions_category (INDEX)

CREATE INDEX idx_infra_category_actions_category ON infra_category_actions USING btree (category);

-- idx_infra_machines_certificate_id (INDEX)

CREATE INDEX idx_infra_machines_certificate_id ON infra_machines USING btree (certificate_id) WHERE (certificate_id IS NOT NULL);

-- idx_infra_machines_parent_id (INDEX)

CREATE INDEX idx_infra_machines_parent_id ON infra_machines USING btree (parent_id) WHERE (parent_id IS NOT NULL);

-- idx_infra_machines_runs_action_id (INDEX)

CREATE INDEX idx_infra_machines_runs_action_id ON infra_machines_runs USING btree (action_id);

-- idx_infra_machines_runs_machine_started (INDEX)

CREATE INDEX idx_infra_machines_runs_machine_started ON infra_machines_runs USING btree (machine_id, started_at DESC);

-- idx_infra_machines_type_id (INDEX)

CREATE INDEX idx_infra_machines_type_id ON infra_machines USING btree (type_id);

-- idx_infra_named_type_actions_named_type (INDEX)

CREATE INDEX idx_infra_named_type_actions_named_type ON infra_named_type_actions USING btree (named_type_id);

-- idx_infra_named_types_sub_type_id (INDEX)

CREATE INDEX idx_infra_named_types_sub_type_id ON infra_named_types USING btree (sub_type_id) WHERE (sub_type_id IS NOT NULL);

-- idx_infra_named_types_type_id (INDEX)

CREATE INDEX idx_infra_named_types_type_id ON infra_named_types USING btree (type_id);

-- idx_infra_servers_certificate_id (INDEX)

CREATE INDEX idx_infra_servers_certificate_id ON infra_machines USING btree (certificate_id) WHERE (certificate_id IS NOT NULL);

-- idx_instances_group_id (INDEX)

CREATE INDEX idx_instances_group_id ON instances USING btree (group_id);

-- idx_launched_tasks_dockerfile (INDEX)

CREATE INDEX idx_launched_tasks_dockerfile ON launched_tasks USING btree (dockerfile_id);

-- idx_launched_tasks_status (INDEX)

CREATE INDEX idx_launched_tasks_status ON launched_tasks USING btree (status);

-- idx_mcp_servers_repo (INDEX)

CREATE INDEX idx_mcp_servers_repo ON mcp_servers USING btree (repo);

-- idx_outbound_hooks_pending (INDEX)

CREATE INDEX idx_outbound_hooks_pending ON outbound_hooks USING btree (next_retry_at) WHERE ((status)::text = 'pending'::text);

-- idx_project_deployments_project_id (INDEX)

CREATE INDEX idx_project_deployments_project_id ON project_deployments USING btree (project_id);

-- idx_project_deployments_user_id (INDEX)

CREATE INDEX idx_project_deployments_user_id ON project_deployments USING btree (user_id);

-- idx_project_group_runtimes_group (INDEX)

CREATE INDEX idx_project_group_runtimes_group ON project_group_runtimes USING btree (group_id);

-- idx_project_group_runtimes_machine (INDEX)

CREATE INDEX idx_project_group_runtimes_machine ON project_group_runtimes USING btree (machine_id) WHERE (machine_id IS NOT NULL);

-- idx_project_group_runtimes_not_deleted (INDEX)

CREATE INDEX idx_project_group_runtimes_not_deleted ON project_group_runtimes USING btree (group_id, seq DESC) WHERE (deleted_at IS NULL);

-- idx_project_group_runtimes_runtime (INDEX)

CREATE INDEX idx_project_group_runtimes_runtime ON project_group_runtimes USING btree (project_runtime_id);

-- idx_project_runtimes_deployment (INDEX)

CREATE INDEX idx_project_runtimes_deployment ON project_runtimes USING btree (deployment_id) WHERE (deployment_id IS NOT NULL);

-- idx_project_runtimes_not_deleted (INDEX)

CREATE INDEX idx_project_runtimes_not_deleted ON project_runtimes USING btree (project_id, seq DESC) WHERE (deleted_at IS NULL);

-- idx_project_runtimes_project (INDEX)

CREATE INDEX idx_project_runtimes_project ON project_runtimes USING btree (project_id);

-- idx_role_sections_role_pos (INDEX)

CREATE INDEX idx_role_sections_role_pos ON role_sections USING btree (role_id, "position");

-- idx_scripts_execute_on_types_named (INDEX)

CREATE INDEX idx_scripts_execute_on_types_named ON scripts USING btree (execute_on_types_named) WHERE (execute_on_types_named IS NOT NULL);

-- idx_secrets_var_name (INDEX)

CREATE INDEX idx_secrets_var_name ON secrets USING btree (var_name);

-- idx_sessions_api_key (INDEX)

CREATE INDEX idx_sessions_api_key ON sessions USING btree (api_key_id, status);

-- idx_sessions_expires (INDEX)

CREATE INDEX idx_sessions_expires ON sessions USING btree (expires_at) WHERE (status = 'active'::text);

-- idx_tasks_action_exec (INDEX)

CREATE INDEX idx_tasks_action_exec ON tasks USING btree (agflow_action_execution_id) WHERE (agflow_action_execution_id IS NOT NULL);

-- idx_tasks_pending (INDEX)

CREATE INDEX idx_tasks_pending ON tasks USING btree (kind, status, created_at) WHERE ((status)::text = ANY ((ARRAY['pending'::character varying, 'running'::character varying])::text[]));

-- idx_tasks_runtime (INDEX)

CREATE INDEX idx_tasks_runtime ON tasks USING btree (project_runtime_id) WHERE (project_runtime_id IS NOT NULL);

-- idx_tasks_session (INDEX)

CREATE INDEX idx_tasks_session ON tasks USING btree (session_id) WHERE (session_id IS NOT NULL);

-- idx_user_identities_lookup (INDEX)

CREATE INDEX idx_user_identities_lookup ON user_identities USING btree (provider, subject);

-- idx_user_identities_user (INDEX)

CREATE INDEX idx_user_identities_user ON user_identities USING btree (user_id);

-- idx_user_secrets_user (INDEX)

CREATE INDEX idx_user_secrets_user ON user_secrets USING btree (user_id);

-- idx_users_email (INDEX)

CREATE INDEX idx_users_email ON users USING btree (email);

-- idx_users_status (INDEX)

CREATE INDEX idx_users_status ON users USING btree (status);

-- uniq_machine_user_env (INDEX)

CREATE UNIQUE INDEX uniq_machine_user_env ON infra_machines USING btree (user_id, environment) WHERE (user_id IS NOT NULL);

-- group_scripts trg_group_scripts_updated_at (TRIGGER)

CREATE TRIGGER trg_group_scripts_updated_at BEFORE UPDATE ON group_scripts FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- groups trg_groups_updated_at (TRIGGER)

CREATE TRIGGER trg_groups_updated_at BEFORE UPDATE ON groups FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- infra_certificates trg_infra_certificates_updated_at (TRIGGER)

CREATE TRIGGER trg_infra_certificates_updated_at BEFORE UPDATE ON infra_certificates FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- infra_machines trg_infra_machines_updated_at (TRIGGER)

CREATE TRIGGER trg_infra_machines_updated_at BEFORE UPDATE ON infra_machines FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- infra_named_type_actions trg_infra_named_type_actions_updated_at (TRIGGER)

CREATE TRIGGER trg_infra_named_type_actions_updated_at BEFORE UPDATE ON infra_named_type_actions FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- infra_named_types trg_infra_named_types_updated_at (TRIGGER)

CREATE TRIGGER trg_infra_named_types_updated_at BEFORE UPDATE ON infra_named_types FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- instances trg_instances_updated_at (TRIGGER)

CREATE TRIGGER trg_instances_updated_at BEFORE UPDATE ON instances FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- outbound_hooks trg_outbound_hooks_updated_at (TRIGGER)

CREATE TRIGGER trg_outbound_hooks_updated_at BEFORE UPDATE ON outbound_hooks FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- project_deployments trg_project_deployments_updated_at (TRIGGER)

CREATE TRIGGER trg_project_deployments_updated_at BEFORE UPDATE ON project_deployments FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- project_group_runtimes trg_project_group_runtimes_updated_at (TRIGGER)

CREATE TRIGGER trg_project_group_runtimes_updated_at BEFORE UPDATE ON project_group_runtimes FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- project_runtimes trg_project_runtimes_updated_at (TRIGGER)

CREATE TRIGGER trg_project_runtimes_updated_at BEFORE UPDATE ON project_runtimes FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- projects trg_projects_updated_at (TRIGGER)

CREATE TRIGGER trg_projects_updated_at BEFORE UPDATE ON projects FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- scripts trg_scripts_updated_at (TRIGGER)

CREATE TRIGGER trg_scripts_updated_at BEFORE UPDATE ON scripts FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- tasks trg_tasks_updated_at (TRIGGER)

CREATE TRIGGER trg_tasks_updated_at BEFORE UPDATE ON tasks FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- agent_message_delivery agent_message_delivery_msg_id_fkey (FK CONSTRAINT)

ALTER TABLE ONLY agent_message_delivery
    ADD CONSTRAINT agent_message_delivery_msg_id_fkey FOREIGN KEY (msg_id) REFERENCES agent_messages(msg_id) ON DELETE CASCADE;

-- agent_messages agent_messages_parent_msg_id_fkey (FK CONSTRAINT)

ALTER TABLE ONLY agent_messages
    ADD CONSTRAINT agent_messages_parent_msg_id_fkey FOREIGN KEY (parent_msg_id) REFERENCES agent_messages(msg_id);

-- agents_instances agents_instances_agent_id_fkey (FK CONSTRAINT)

ALTER TABLE ONLY agents_instances
    ADD CONSTRAINT agents_instances_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES agents_catalog(slug) ON DELETE RESTRICT;

-- agents_instances agents_instances_session_id_fkey (FK CONSTRAINT)

ALTER TABLE ONLY agents_instances
    ADD CONSTRAINT agents_instances_session_id_fkey FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE;

-- api_keys api_keys_owner_id_fkey (FK CONSTRAINT)

ALTER TABLE ONLY api_keys
    ADD CONSTRAINT api_keys_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE;

-- deployment_instances deployment_instances_deployment_id_fkey (FK CONSTRAINT)

ALTER TABLE ONLY deployment_instances
    ADD CONSTRAINT deployment_instances_deployment_id_fkey FOREIGN KEY (deployment_id) REFERENCES project_deployments(id) ON DELETE CASCADE;

-- deployment_instances deployment_instances_instance_id_fkey (FK CONSTRAINT)

ALTER TABLE ONLY deployment_instances
    ADD CONSTRAINT deployment_instances_instance_id_fkey FOREIGN KEY (instance_id) REFERENCES instances(id) ON DELETE CASCADE;

-- deployment_instances deployment_instances_machine_id_fkey (FK CONSTRAINT)

ALTER TABLE ONLY deployment_instances
    ADD CONSTRAINT deployment_instances_machine_id_fkey FOREIGN KEY (machine_id) REFERENCES infra_machines(id) ON DELETE SET NULL;

-- dockerfile_builds dockerfile_builds_dockerfile_id_fkey (FK CONSTRAINT)

ALTER TABLE ONLY dockerfile_builds
    ADD CONSTRAINT dockerfile_builds_dockerfile_id_fkey FOREIGN KEY (dockerfile_id) REFERENCES dockerfiles(id) ON DELETE CASCADE;

-- group_scripts group_scripts_group_id_fkey (FK CONSTRAINT)

ALTER TABLE ONLY group_scripts
    ADD CONSTRAINT group_scripts_group_id_fkey FOREIGN KEY (group_id) REFERENCES groups(id) ON DELETE CASCADE;

-- group_scripts group_scripts_machine_id_fkey (FK CONSTRAINT)

ALTER TABLE ONLY group_scripts
    ADD CONSTRAINT group_scripts_machine_id_fkey FOREIGN KEY (machine_id) REFERENCES infra_machines(id) ON DELETE RESTRICT;

-- group_scripts group_scripts_script_id_fkey (FK CONSTRAINT)

ALTER TABLE ONLY group_scripts
    ADD CONSTRAINT group_scripts_script_id_fkey FOREIGN KEY (script_id) REFERENCES scripts(id) ON DELETE CASCADE;

-- groups groups_machine_id_fkey (FK CONSTRAINT)

ALTER TABLE ONLY groups
    ADD CONSTRAINT groups_machine_id_fkey FOREIGN KEY (machine_id) REFERENCES infra_machines(id) ON DELETE SET NULL;

-- groups groups_project_id_fkey (FK CONSTRAINT)

ALTER TABLE ONLY groups
    ADD CONSTRAINT groups_project_id_fkey FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE;

-- infra_category_actions infra_category_actions_category_fkey (FK CONSTRAINT)

ALTER TABLE ONLY infra_category_actions
    ADD CONSTRAINT infra_category_actions_category_fkey FOREIGN KEY (category) REFERENCES infra_categories(name) ON UPDATE CASCADE ON DELETE CASCADE;

-- infra_machines_runs infra_machines_runs_action_id_fkey (FK CONSTRAINT)

ALTER TABLE ONLY infra_machines_runs
    ADD CONSTRAINT infra_machines_runs_action_id_fkey FOREIGN KEY (action_id) REFERENCES infra_named_type_actions(id) ON DELETE RESTRICT;

-- infra_machines_runs infra_machines_runs_machine_id_fkey (FK CONSTRAINT)

ALTER TABLE ONLY infra_machines_runs
    ADD CONSTRAINT infra_machines_runs_machine_id_fkey FOREIGN KEY (machine_id) REFERENCES infra_machines(id) ON DELETE CASCADE;

-- infra_machines infra_machines_type_id_fkey (FK CONSTRAINT)

ALTER TABLE ONLY infra_machines
    ADD CONSTRAINT infra_machines_type_id_fkey FOREIGN KEY (type_id) REFERENCES infra_named_types(id) ON DELETE RESTRICT;

-- infra_machines infra_machines_user_id_fkey (FK CONSTRAINT)

ALTER TABLE ONLY infra_machines
    ADD CONSTRAINT infra_machines_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL;

-- infra_named_type_actions infra_named_type_actions_category_action_id_fkey (FK CONSTRAINT)

ALTER TABLE ONLY infra_named_type_actions
    ADD CONSTRAINT infra_named_type_actions_category_action_id_fkey FOREIGN KEY (category_action_id) REFERENCES infra_category_actions(id) ON DELETE CASCADE;

-- infra_named_type_actions infra_named_type_actions_named_type_id_fkey (FK CONSTRAINT)

ALTER TABLE ONLY infra_named_type_actions
    ADD CONSTRAINT infra_named_type_actions_named_type_id_fkey FOREIGN KEY (named_type_id) REFERENCES infra_named_types(id) ON DELETE CASCADE;

-- infra_named_types infra_named_types_sub_type_id_fkey (FK CONSTRAINT)

ALTER TABLE ONLY infra_named_types
    ADD CONSTRAINT infra_named_types_sub_type_id_fkey FOREIGN KEY (sub_type_id) REFERENCES infra_named_types(id) ON DELETE SET NULL;

-- infra_named_types infra_named_types_type_id_fkey (FK CONSTRAINT)

ALTER TABLE ONLY infra_named_types
    ADD CONSTRAINT infra_named_types_type_id_fkey FOREIGN KEY (type_id) REFERENCES infra_categories(name) ON UPDATE CASCADE ON DELETE RESTRICT;

-- infra_machines infra_servers_certificate_id_fkey (FK CONSTRAINT)

ALTER TABLE ONLY infra_machines
    ADD CONSTRAINT infra_servers_certificate_id_fkey FOREIGN KEY (certificate_id) REFERENCES infra_certificates(id) ON DELETE SET NULL;

-- infra_machines infra_servers_parent_id_fkey (FK CONSTRAINT)

ALTER TABLE ONLY infra_machines
    ADD CONSTRAINT infra_servers_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES infra_machines(id) ON DELETE SET NULL;

-- instances instances_group_id_fkey (FK CONSTRAINT)

ALTER TABLE ONLY instances
    ADD CONSTRAINT instances_group_id_fkey FOREIGN KEY (group_id) REFERENCES groups(id) ON DELETE CASCADE;

-- mcp_servers mcp_servers_discovery_service_id_fkey (FK CONSTRAINT)

ALTER TABLE ONLY mcp_servers
    ADD CONSTRAINT mcp_servers_discovery_service_id_fkey FOREIGN KEY (discovery_service_id) REFERENCES discovery_services(id) ON DELETE CASCADE;

-- outbound_hooks outbound_hooks_task_id_fkey (FK CONSTRAINT)

ALTER TABLE ONLY outbound_hooks
    ADD CONSTRAINT outbound_hooks_task_id_fkey FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE;

-- project_deployments project_deployments_project_id_fkey (FK CONSTRAINT)

ALTER TABLE ONLY project_deployments
    ADD CONSTRAINT project_deployments_project_id_fkey FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE;

-- project_deployments project_deployments_user_id_fkey (FK CONSTRAINT)

ALTER TABLE ONLY project_deployments
    ADD CONSTRAINT project_deployments_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id);

-- project_group_runtimes project_group_runtimes_group_id_fkey (FK CONSTRAINT)

ALTER TABLE ONLY project_group_runtimes
    ADD CONSTRAINT project_group_runtimes_group_id_fkey FOREIGN KEY (group_id) REFERENCES groups(id) ON DELETE CASCADE;

-- project_group_runtimes project_group_runtimes_machine_id_fkey (FK CONSTRAINT)

ALTER TABLE ONLY project_group_runtimes
    ADD CONSTRAINT project_group_runtimes_machine_id_fkey FOREIGN KEY (machine_id) REFERENCES infra_machines(id) ON DELETE SET NULL;

-- project_group_runtimes project_group_runtimes_project_runtime_id_fkey (FK CONSTRAINT)

ALTER TABLE ONLY project_group_runtimes
    ADD CONSTRAINT project_group_runtimes_project_runtime_id_fkey FOREIGN KEY (project_runtime_id) REFERENCES project_runtimes(id) ON DELETE CASCADE;

-- project_runtimes project_runtimes_deployment_id_fkey (FK CONSTRAINT)

ALTER TABLE ONLY project_runtimes
    ADD CONSTRAINT project_runtimes_deployment_id_fkey FOREIGN KEY (deployment_id) REFERENCES project_deployments(id) ON DELETE SET NULL;

-- project_runtimes project_runtimes_project_id_fkey (FK CONSTRAINT)

ALTER TABLE ONLY project_runtimes
    ADD CONSTRAINT project_runtimes_project_id_fkey FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE;

-- project_runtimes project_runtimes_user_id_fkey (FK CONSTRAINT)

ALTER TABLE ONLY project_runtimes
    ADD CONSTRAINT project_runtimes_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL;

-- scripts scripts_execute_on_types_named_fkey (FK CONSTRAINT)

ALTER TABLE ONLY scripts
    ADD CONSTRAINT scripts_execute_on_types_named_fkey FOREIGN KEY (execute_on_types_named) REFERENCES infra_named_types(id) ON DELETE SET NULL;

-- sessions sessions_api_key_id_fkey (FK CONSTRAINT)

ALTER TABLE ONLY sessions
    ADD CONSTRAINT sessions_api_key_id_fkey FOREIGN KEY (api_key_id) REFERENCES api_keys(id) ON DELETE CASCADE;

-- sessions sessions_project_runtime_id_fkey (FK CONSTRAINT)

ALTER TABLE ONLY sessions
    ADD CONSTRAINT sessions_project_runtime_id_fkey FOREIGN KEY (project_runtime_id) REFERENCES project_runtimes(id) ON DELETE SET NULL;

-- skills skills_discovery_service_id_fkey (FK CONSTRAINT)

ALTER TABLE ONLY skills
    ADD CONSTRAINT skills_discovery_service_id_fkey FOREIGN KEY (discovery_service_id) REFERENCES discovery_services(id) ON DELETE CASCADE;

-- tasks tasks_agent_instance_id_fkey (FK CONSTRAINT)

ALTER TABLE ONLY tasks
    ADD CONSTRAINT tasks_agent_instance_id_fkey FOREIGN KEY (agent_instance_id) REFERENCES agents_instances(id) ON DELETE CASCADE;

-- tasks tasks_project_runtime_id_fkey (FK CONSTRAINT)

ALTER TABLE ONLY tasks
    ADD CONSTRAINT tasks_project_runtime_id_fkey FOREIGN KEY (project_runtime_id) REFERENCES project_runtimes(id) ON DELETE CASCADE;

-- tasks tasks_session_id_fkey (FK CONSTRAINT)

ALTER TABLE ONLY tasks
    ADD CONSTRAINT tasks_session_id_fkey FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE;

-- user_identities user_identities_user_id_fkey (FK CONSTRAINT)

ALTER TABLE ONLY user_identities
    ADD CONSTRAINT user_identities_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;

-- user_secrets user_secrets_user_id_fkey (FK CONSTRAINT)

ALTER TABLE ONLY user_secrets
    ADD CONSTRAINT user_secrets_user_id_fkey FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;

-- users users_approved_by_fkey (FK CONSTRAINT)

ALTER TABLE ONLY users
    ADD CONSTRAINT users_approved_by_fkey FOREIGN KEY (approved_by) REFERENCES users(id);

-- Seeds : types de services natifs (catalogue M3 / catalogues services)
INSERT INTO service_types (name, display_name, is_native, position) VALUES
    ('documentation', 'Documentation',      TRUE, 0),
    ('code',          'Code',               TRUE, 1),
    ('design',        'Maquette/Design',    TRUE, 2),
    ('automation',    'Automatisme',        TRUE, 3),
    ('task_list',     'Liste de tâches',    TRUE, 4),
    ('specs',         'Spécifications',     TRUE, 5),
    ('contract',      'Contrat',            TRUE, 6)
ON CONFLICT (name) DO NOTHING;

-- Seeds : categories d'infrastructure (platform / service)
INSERT INTO infra_categories (name) VALUES
    ('platform'),
    ('service')
ON CONFLICT (name) DO NOTHING;

-- Seeds : actions natives par categorie
INSERT INTO infra_category_actions (category, name) VALUES
    ('platform', 'destroy'),
    ('service',  'install')
ON CONFLICT (category, name) DO NOTHING;

-- Seeds : timeouts supervision (M6)
INSERT INTO platform_config (key, value) VALUES
    ('session_idle_timeout_s',               '120'),
    ('agent_idle_timeout_s',                 '600'),
    ('supervision_reaper_interval_s',        '20'),
    ('supervision_reclaim_interval_s',       '15'),
    ('supervision_reclaim_stale_threshold_s','30')
ON CONFLICT (key) DO NOTHING;
