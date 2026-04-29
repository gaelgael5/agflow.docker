-- L1 du contrat workflow `docker-orchestration-flow.md` v5.
-- Pose les fondations DB pour l'orchestration M2M ag.flow ↔ agflow.docker :
-- session avec callback HMAC + lien runtime, resources enrichies (mcp_bindings,
-- connection_params, setup_steps, status), tasks polymorphe (1 ligne par
-- opération asynchrone), HMAC keys, queue de hooks outbound.
--
-- L2 ajoutera le worker provisioning + les endpoints workflow.
-- L3 ajoutera le worker hook dispatcher + les routes /sessions/work.

-- ── Sessions : porter callback HMAC + lien project_runtime ──────────────────
ALTER TABLE sessions
    ADD COLUMN IF NOT EXISTS project_runtime_id UUID
        REFERENCES project_runtimes(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS callback_url TEXT,
    ADD COLUMN IF NOT EXISTS callback_hmac_key_id VARCHAR(64);

COMMENT ON COLUMN sessions.project_runtime_id IS
    'Optionnel — si non null, les agents de cette session reçoivent les MCP des resources du runtime à leur instanciation';
COMMENT ON COLUMN sessions.callback_url IS
    'Base URL ag.flow pour les hooks task-completed (workflow contract v5)';
COMMENT ON COLUMN sessions.callback_hmac_key_id IS
    'Identifiant logique de la clé HMAC à utiliser pour signer les hooks';

-- ── Product instances : enrichir pour les resources contractuelles ─────────
ALTER TABLE instances
    ADD COLUMN IF NOT EXISTS connection_params JSONB,
    ADD COLUMN IF NOT EXISTS mcp_bindings JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS setup_steps JSONB NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS provisioning_status VARCHAR(32)
        NOT NULL DEFAULT 'ready'
        CHECK (provisioning_status IN ('provisioning', 'ready', 'pending_setup', 'failed'));

COMMENT ON COLUMN instances.mcp_bindings IS
    'Liste des MCP servers exposés par cette resource (injectés dans les agents des sessions liées au runtime)';
COMMENT ON COLUMN instances.connection_params IS
    'Params de connexion exposés par la resource après provisioning (urls, var names, etc.)';
COMMENT ON COLUMN instances.setup_steps IS
    'Instructions templated Jinja (résolues côté Docker) à effectuer manuellement par l''utilisateur après provisioning';

-- ── Agents instances : trace de l'injection MCP ─────────────────────────────
ALTER TABLE agents_instances
    ADD COLUMN IF NOT EXISTS mcp_bindings_injected JSONB
        NOT NULL DEFAULT '[]'::jsonb;

COMMENT ON COLUMN agents_instances.mcp_bindings_injected IS
    'MCP réellement injectés dans le container de l''agent (catalogue agent + resources du runtime). Pour transparence côté workflow.';

-- ── Tasks : pivot d'asynchronisme (1 ligne par opération async ou sync) ────
CREATE TABLE IF NOT EXISTS tasks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kind            VARCHAR(64) NOT NULL
                    CHECK (kind IN (
                        'runtime_provision',
                        'session_create',
                        'agent_create',
                        'session_work'
                    )),
    project_runtime_id      UUID REFERENCES project_runtimes(id) ON DELETE CASCADE,
    session_id              UUID REFERENCES sessions(id) ON DELETE CASCADE,
    agent_instance_id       UUID REFERENCES agents_instances(id) ON DELETE CASCADE,
    status          VARCHAR(32) NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'running', 'completed', 'failed', 'cancelled')),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    result          JSONB,
    error           JSONB,
    -- Champs réservés _agflow_* propagés depuis l'instruction du work
    agflow_action_execution_id  UUID,
    agflow_correlation_id       UUID,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tasks_pending
    ON tasks(kind, status, created_at)
    WHERE status IN ('pending', 'running');
CREATE INDEX IF NOT EXISTS idx_tasks_session
    ON tasks(session_id) WHERE session_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tasks_runtime
    ON tasks(project_runtime_id) WHERE project_runtime_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tasks_action_exec
    ON tasks(agflow_action_execution_id) WHERE agflow_action_execution_id IS NOT NULL;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_tasks_updated_at') THEN
        CREATE TRIGGER trg_tasks_updated_at
            BEFORE UPDATE ON tasks
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
END $$;

-- ── HMAC keys : clés partagées avec ag.flow pour signer les hooks ──────────
CREATE TABLE IF NOT EXISTS hmac_keys (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key_id              VARCHAR(64) NOT NULL UNIQUE,
    -- Chiffrée Fernet (cf. crypto_service)
    key_value_encrypted BYTEA NOT NULL,
    description         TEXT NOT NULL DEFAULT '',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    rotated_at          TIMESTAMPTZ
);

COMMENT ON TABLE hmac_keys IS
    'Clés HMAC partagées avec ag.flow (workflow). Référencées par sessions.callback_hmac_key_id.';

-- ── Outbound hooks : queue + retry pour les hooks task-completed ───────────
CREATE TABLE IF NOT EXISTS outbound_hooks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- = X-Agflow-Hook-Id, UNIQUE pour idempotence côté ag.flow
    hook_id         UUID NOT NULL UNIQUE,
    task_id         UUID REFERENCES tasks(id) ON DELETE CASCADE,
    callback_url    TEXT NOT NULL,
    hmac_key_id     VARCHAR(64) NOT NULL,
    payload         JSONB NOT NULL,
    attempt_number  INTEGER NOT NULL DEFAULT 0,
    status          VARCHAR(32) NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'delivered', 'dead')),
    last_response_code  INTEGER,
    last_attempt_at     TIMESTAMPTZ,
    next_retry_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    error_message       TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_outbound_hooks_pending
    ON outbound_hooks(next_retry_at)
    WHERE status = 'pending';

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_outbound_hooks_updated_at') THEN
        CREATE TRIGGER trg_outbound_hooks_updated_at
            BEFORE UPDATE ON outbound_hooks
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
END $$;
