# Phase 5a — Module 4 (Agent Composition — data layer) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the backend data layer, composition logic, config-preview assembler and a minimal (volontairement laid) CRUD frontend for Module 4 (Agent Composition), so that an agent can be defined (Dockerfile + Role + N MCPs with per-agent overrides + N Skills + lifecycle params), duplicated, validated, and its config directory previewed — without the rich visual builder, which is deferred to Phase 5b after UX/UI mockups.

**Architecture:** 3 new Postgres tables (`agents`, `agent_mcp_servers`, `agent_skills`) with FK to existing M0-M3 tables. A `composition_builder` service aggregates role prompt (via existing `prompt_generator.assemble_source_markdown`), MCP configs (global params merged with per-agent overrides), skills content, and resolves secrets via Module 0 — returning a JSON preview (no disk write, no container launch). Image freshness derived from `dockerfile_builds.content_hash` (🔴 missing / 🟠 stale / 🟢 fresh). Frontend: 2 pages (`AgentsPage` list + `AgentEditorPage` form), deliberately styled with raw HTML like the other M0-M3 pages — design polish is Phase 5b.

**Tech Stack:** Same as prior phases — FastAPI + asyncpg + Pydantic v2 + pytest ; React 18 + TanStack Query + i18next + Vitest.

---

## Scope

### In scope (5a)
- `agents` table + 2 N-N tables (`agent_mcp_servers`, `agent_skills`)
- Backend CRUD (list / get / create / update / delete / duplicate)
- Image freshness indicator (🔴/🟠/🟢) derived from `dockerfile_builds`
- `composition_builder.build_preview(agent_id)` → returns `{prompt_md, mcp_json, tools_json, env_file, skills, validation_errors}`
- Admin router with endpoints
- Frontend minimal CRUD (2 pages, raw HTML, no design system)
- Tests TDD backend + minimal frontend tests
- Registered under `/agents` route + nav link on HomePage

### Out of scope (deferred to 5b or later phases)
- Rich visual builder (drag & drop, brique representation) → 5b after mockups
- Session de test (container launch + WebSocket streaming) → Phase 8 (vertical E2E)
- Personnalisation par mission → 5b or Phase 6
- Communication inter-agents / Tools normalisés → Phases 6/7
- Writing the config directory to disk → Phase 8 (actual container launch)
- Agent-scoped secrets UI (schema exists, but no M4 UI for them)

---

## File Structure

### Backend — new files
- `backend/migrations/013_agents.sql`
- `backend/migrations/014_agent_mcp_servers.sql`
- `backend/migrations/015_agent_skills.sql`
- `backend/src/agflow/schemas/agents.py`
- `backend/src/agflow/services/agents_service.py`
- `backend/src/agflow/services/composition_builder.py`
- `backend/src/agflow/api/admin/agents.py`
- `backend/tests/test_agents_service.py`
- `backend/tests/test_composition_builder.py`
- `backend/tests/test_agents_endpoint.py`

### Backend — modified files
- `backend/src/agflow/main.py` (register router)

### Frontend — new files
- `frontend/src/lib/agentsApi.ts`
- `frontend/src/hooks/useAgents.ts`
- `frontend/src/pages/AgentsPage.tsx`
- `frontend/src/pages/AgentEditorPage.tsx`
- `frontend/tests/pages/AgentsPage.test.tsx`
- `frontend/tests/hooks/useAgents.test.tsx`

### Frontend — modified files
- `frontend/src/i18n/fr.json` + `en.json` (add `agents.*`, `agent_editor.*`)
- `frontend/src/App.tsx` (2 new routes)
- `frontend/src/pages/HomePage.tsx` (nav link)

---

## Data model (locked decisions)

### `agents` table (013)
```sql
CREATE TABLE agents (
    id                      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    slug                    TEXT UNIQUE NOT NULL,
    display_name            TEXT NOT NULL,
    description             TEXT NOT NULL DEFAULT '',
    dockerfile_id           TEXT NOT NULL REFERENCES dockerfiles(id) ON DELETE RESTRICT,
    role_id                 TEXT NOT NULL REFERENCES roles(id)       ON DELETE RESTRICT,
    -- lifecycle params (flat columns — keep schema queryable)
    env_vars                JSONB NOT NULL DEFAULT '{}'::jsonb,     -- {"KEY":"value" or "$VAR"}
    timeout_seconds         INTEGER NOT NULL DEFAULT 3600 CHECK (timeout_seconds > 0),
    workspace_path          TEXT   NOT NULL DEFAULT '/workspace',
    network_mode            TEXT   NOT NULL DEFAULT 'bridge'
                            CHECK (network_mode IN ('bridge', 'host', 'none')),
    graceful_shutdown_secs  INTEGER NOT NULL DEFAULT 30 CHECK (graceful_shutdown_secs >= 0),
    force_kill_delay_secs   INTEGER NOT NULL DEFAULT 10 CHECK (force_kill_delay_secs >= 0),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_agents_slug         ON agents(slug);
CREATE INDEX idx_agents_dockerfile   ON agents(dockerfile_id);
CREATE INDEX idx_agents_role         ON agents(role_id);
```

### `agent_mcp_servers` table (014)
```sql
CREATE TABLE agent_mcp_servers (
    agent_id             UUID NOT NULL REFERENCES agents(id)     ON DELETE CASCADE,
    mcp_server_id        UUID NOT NULL REFERENCES mcp_servers(id) ON DELETE RESTRICT,
    parameters_override  JSONB NOT NULL DEFAULT '{}'::jsonb,
    position             INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (agent_id, mcp_server_id)
);

CREATE INDEX idx_agent_mcp_agent ON agent_mcp_servers(agent_id, position);
```

### `agent_skills` table (015)
```sql
CREATE TABLE agent_skills (
    agent_id  UUID NOT NULL REFERENCES agents(id)  ON DELETE CASCADE,
    skill_id  UUID NOT NULL REFERENCES skills(id)  ON DELETE RESTRICT,
    position  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (agent_id, skill_id)
);

CREATE INDEX idx_agent_skills_agent ON agent_skills(agent_id, position);
```

---

## Dependencies on prior modules (already verified)

- `dockerfile_builds(content_hash, status)` + `build_service.compute_hash(files)` + `build_service.get_latest_build(dockerfile_id)` — for image freshness
- `role_documents_service.list_for_role(role_id)` + `prompt_generator.assemble_source_markdown(role, docs)` — for compiled prompt.md
- `secrets_service.resolve_env([names])` + `resolve_status([names])` — for env resolution
- `mcp_servers.parameters` (global default) — merged with per-agent `parameters_override`
- `skills.content_md` — bundled as-is in preview

---

## Tasks

### Task 1: Migrations 013 + 014 + 015

**Files:**
- Create: `backend/migrations/013_agents.sql`
- Create: `backend/migrations/014_agent_mcp_servers.sql`
- Create: `backend/migrations/015_agent_skills.sql`

- [ ] **Step 1:** Write the 3 SQL files using the exact DDL from the "Data model" section above.

- [ ] **Step 2:** Apply against dev Postgres:
  ```bash
  cd /e/srcs/agflow.docker/backend && uv run python -m agflow.db.migrations
  ```
  Expected: `applied=['013_agents','014_agent_mcp_servers','015_agent_skills']`.

- [ ] **Step 3:** Commit:
  ```bash
  git add backend/migrations/013_agents.sql backend/migrations/014_agent_mcp_servers.sql backend/migrations/015_agent_skills.sql
  git commit -m "feat(m4): migrations 013+014+015 for agents / mcp bindings / skill bindings"
  ```

---

### Task 2: Pydantic schemas

**File:** `backend/src/agflow/schemas/agents.py`

- [ ] **Step 1:** Create the schemas file with:
  - `NetworkMode = Literal["bridge","host","none"]`
  - `ImageStatus = Literal["missing","stale","fresh"]`
  - `AgentMCPBinding(BaseModel)`: `mcp_server_id: UUID`, `parameters_override: dict = {}`, `position: int = 0`
  - `AgentSkillBinding(BaseModel)`: `skill_id: UUID`, `position: int = 0`
  - `AgentCreate(BaseModel)`: `slug` (validator: `^[a-z0-9-]{1,64}$`), `display_name`, `description=""`, `dockerfile_id`, `role_id`, `env_vars: dict = {}`, lifecycle params with defaults, `mcp_bindings: list[AgentMCPBinding] = []`, `skill_bindings: list[AgentSkillBinding] = []`
  - `AgentUpdate(BaseModel)`: same fields as AgentCreate except `slug`
  - `AgentSummary(BaseModel)`: flat row without bindings (for list view)
  - `AgentDetail(AgentSummary)`: adds `mcp_bindings` and `skill_bindings` and `image_status: ImageStatus`
  - `ConfigPreview(BaseModel)`: `prompt_md: str`, `mcp_json: dict`, `tools_json: list[dict]`, `env_file: str`, `skills: list[dict]` (each `{skill_id, name, content_md}`), `validation_errors: list[str]`

- [ ] **Step 2:** Commit:
  ```bash
  git add backend/src/agflow/schemas/agents.py
  git commit -m "feat(m4): Pydantic schemas for agents / bindings / config preview"
  ```

---

### Task 3: `agents_service` CRUD + duplicate (TDD)

**Files:**
- Create: `backend/src/agflow/services/agents_service.py`
- Create: `backend/tests/test_agents_service.py`

- [ ] **Step 1:** Write failing tests covering:
  - `create(payload)` inserts agent + bindings atomically (1 tx) and returns `AgentDetail`
  - `create()` raises `DuplicateAgentError` on slug collision
  - `create()` raises `InvalidReferenceError` if `dockerfile_id` / `role_id` / any `mcp_server_id` / any `skill_id` does not exist
  - `list_all()` returns sorted by `display_name`
  - `get_by_id(uuid)` returns `AgentDetail` with bindings; raises `AgentNotFoundError` if missing
  - `update(uuid, payload)` replaces bindings (delete+insert in a tx)
  - `delete(uuid)` cascades bindings
  - `duplicate(uuid, new_slug, new_display_name)` clones agent + all bindings (new UUID)

- [ ] **Step 2:** Run tests to confirm they fail:
  ```bash
  cd /e/srcs/agflow.docker/backend && uv run pytest tests/test_agents_service.py -v
  ```

- [ ] **Step 3:** Implement `agents_service.py`:
  - Exception classes: `AgentNotFoundError`, `DuplicateAgentError`, `InvalidReferenceError`
  - Use a single `asyncpg` transaction for `create` / `update` / `duplicate` / `delete`
  - Column order constant `_COLS = "id, slug, display_name, description, dockerfile_id, role_id, env_vars, timeout_seconds, workspace_path, network_mode, graceful_shutdown_secs, force_kill_delay_secs, created_at, updated_at"`
  - `_row(row)` helper → `AgentSummary`
  - `_load_bindings(conn, agent_id)` fetches ordered bindings
  - `image_status(dockerfile_id)` async helper → calls `build_service.get_latest_build` + compares to current `dockerfile_files` hash via `build_service.compute_hash` — returns `"missing" | "stale" | "fresh"`

- [ ] **Step 4:** Run tests to confirm they pass.

- [ ] **Step 5:** Commit:
  ```bash
  git add backend/src/agflow/services/agents_service.py backend/tests/test_agents_service.py
  git commit -m "feat(m4): agents_service CRUD + duplicate + image_status (TDD)"
  ```

---

### Task 4: `composition_builder.build_preview` (TDD)

**Files:**
- Create: `backend/src/agflow/services/composition_builder.py`
- Create: `backend/tests/test_composition_builder.py`

- [ ] **Step 1:** Write failing tests covering:
  - `build_preview(agent_id)` returns `ConfigPreview` with:
    - `prompt_md` = result of `prompt_generator.assemble_source_markdown(role, docs)`
    - `mcp_json` = `{"mcpServers": {name: {transport, package_id, repo, parameters}}}` — parameters = global merged with per-agent overrides
    - `tools_json` = list of `{name, type:"mcp", source: mcp_name, description}`
    - `env_file` = `KEY=value\n...` from `env_vars` (literal values + `$VAR` resolved via secrets)
    - `skills` = list of `{skill_id, name, content_md}`
    - `validation_errors` = [] when everything is OK
  - `build_preview` reports errors (but does not raise) when:
    - A referenced secret is missing → `"Missing secret: NAME"`
    - Image is not built (`image_status == "missing"`) → `"Docker image not built. Run a build in Module 1."`
    - Image is stale → `"Docker image is stale. Rebuild in Module 1."`
  - Use mocks for `secrets_service.resolve_env`, `role_documents_service.list_for_role`, `build_service.get_latest_build`

- [ ] **Step 2:** Run tests → fail.

- [ ] **Step 3:** Implement `composition_builder.py`:
  - `async def build_preview(agent_id: UUID) -> ConfigPreview`
  - Load agent + bindings via `agents_service.get_by_id`
  - Load role via existing `roles_service.get_by_id` + documents via `role_documents_service.list_for_role`
  - Build `prompt_md` via `prompt_generator.assemble_source_markdown`
  - For each MCP binding: fetch `mcp_servers` row, merge `parameters` ← `parameters_override`, build entry under `mcpServers[name]`
  - Build `tools_json` list (one entry per MCP)
  - For each skill binding: fetch `skills` row, append `{skill_id, name, content_md}`
  - Parse `env_vars`: literal strings kept as-is, values starting with `$` are secret names to resolve; collect all needed secret names, call `secrets_service.resolve_env` inside a `try/except` → on `SecretNotFoundError` add a validation error and continue with best-effort env file
  - Build `env_file` string; values that failed to resolve rendered as `KEY=<missing>` and validation error added
  - Compute `image_status`, append validation errors if not `fresh`
  - Return `ConfigPreview(...)` (no raise)

- [ ] **Step 4:** Run tests → pass.

- [ ] **Step 5:** Commit:
  ```bash
  git add backend/src/agflow/services/composition_builder.py backend/tests/test_composition_builder.py
  git commit -m "feat(m4): composition_builder.build_preview (TDD)"
  ```

---

### Task 5: Admin router + endpoint tests (TDD)

**Files:**
- Create: `backend/src/agflow/api/admin/agents.py`
- Create: `backend/tests/test_agents_endpoint.py`
- Modify: `backend/src/agflow/main.py`

- [ ] **Step 1:** Write failing integration tests using the existing fixtures pattern from `test_catalogs_endpoint.py` (drop-and-recreate schema, login, call endpoints). Cover:
  - `POST /api/admin/agents` → 201 with detail
  - `POST /api/admin/agents` duplicate slug → 409
  - `POST /api/admin/agents` with unknown `dockerfile_id` → 400
  - `GET /api/admin/agents` → lists
  - `GET /api/admin/agents/{id}` → 200 with bindings + `image_status`
  - `PUT /api/admin/agents/{id}` replaces bindings
  - `POST /api/admin/agents/{id}/duplicate` → 201 with new slug
  - `DELETE /api/admin/agents/{id}` → 204
  - `GET /api/admin/agents/{id}/config-preview` → 200 with `ConfigPreview` (use mocked `secrets_service` / `build_service` where relevant)

- [ ] **Step 2:** Implement `api/admin/agents.py`:
  - `router = APIRouter(prefix="/api/admin/agents", tags=["admin-agents"], dependencies=[Depends(require_admin)])`
  - Endpoints: `list_agents`, `create_agent`, `get_agent`, `update_agent`, `delete_agent`, `duplicate_agent`, `preview_agent_config`
  - Map service exceptions → HTTPException:
    - `DuplicateAgentError` → 409
    - `InvalidReferenceError` → 400
    - `AgentNotFoundError` → 404

- [ ] **Step 3:** Register router in `main.py`:
  ```python
  from agflow.api.admin.agents import router as admin_agents_router
  ...
  app.include_router(admin_agents_router)
  ```

- [ ] **Step 4:** Run tests → pass. Then full backend suite:
  ```bash
  cd /e/srcs/agflow.docker/backend && uv run pytest -q
  ```

- [ ] **Step 5:** Commit:
  ```bash
  git add backend/src/agflow/api/admin/agents.py backend/src/agflow/main.py backend/tests/test_agents_endpoint.py
  git commit -m "feat(m4): admin agents router + endpoint tests"
  ```

---

### Task 6: Frontend i18n + API client + hooks

**Files:**
- Modify: `frontend/src/i18n/fr.json`, `en.json`
- Create: `frontend/src/lib/agentsApi.ts`
- Create: `frontend/src/hooks/useAgents.ts`

- [ ] **Step 1:** Add to both i18n files sections for `agents` (page_title, empty, columns, create_button, image_status: {missing, stale, fresh}) and `agent_editor` (title, general, dockerfile, role, mcps, skills, lifecycle, env_vars, save, cancel, preview, duplicate).

- [ ] **Step 2:** Create `lib/agentsApi.ts` exporting:
  - Interfaces: `AgentSummary`, `AgentDetail`, `AgentMCPBinding`, `AgentSkillBinding`, `ConfigPreview`, `ImageStatus`
  - `agentsApi` object with: `list()`, `get(id)`, `create(payload)`, `update(id, payload)`, `remove(id)`, `duplicate(id, slug, display_name)`, `configPreview(id)`

- [ ] **Step 3:** Create `hooks/useAgents.ts` with 3 React Query hooks: `useAgents()` (list), `useAgent(id)` (detail), `useConfigPreview(id)` (with `enabled: false` — triggered manually via `refetch`).

- [ ] **Step 4:** Commit:
  ```bash
  git add frontend/src/i18n/fr.json frontend/src/i18n/en.json frontend/src/lib/agentsApi.ts frontend/src/hooks/useAgents.ts
  git commit -m "feat(m4): frontend i18n + agentsApi + React Query hooks"
  ```

---

### Task 7: `AgentsPage` list view (TDD)

**Files:**
- Create: `frontend/src/pages/AgentsPage.tsx`
- Create: `frontend/tests/pages/AgentsPage.test.tsx`

- [ ] **Step 1:** Write failing tests covering:
  - Empty state (no agents)
  - Renders a table row per agent with slug / display_name / dockerfile_id / role_id / image_status badge / actions (Edit, Duplicate, Delete)
  - "Create agent" button navigates to `/agents/new`

- [ ] **Step 2:** Implement `AgentsPage.tsx` with raw HTML table (same style as `DiscoveryServicesPage`).

- [ ] **Step 3:** Run frontend tests → pass.

- [ ] **Step 4:** Commit:
  ```bash
  git add frontend/src/pages/AgentsPage.tsx frontend/tests/pages/AgentsPage.test.tsx
  git commit -m "feat(m4): AgentsPage list view with raw table"
  ```

---

### Task 8: `AgentEditorPage` form (create + edit)

**Files:**
- Create: `frontend/src/pages/AgentEditorPage.tsx`

- [ ] **Step 1:** Implement a single form component that handles both `/agents/new` and `/agents/:id`. Sections (just `<fieldset>` — no design):
  1. **General** — slug (disabled on edit), display_name, description
  2. **Dockerfile** — dropdown populated from `GET /api/admin/dockerfiles`
  3. **Role** — dropdown populated from `GET /api/admin/roles`
  4. **MCP servers** — multi-select with per-row `parameters_override` textarea (JSON)
  5. **Skills** — multi-select ordered list
  6. **Lifecycle** — env_vars (key/value list), timeout, workspace_path, network_mode dropdown, graceful_shutdown_secs, force_kill_delay_secs
  7. **Actions bar** — Save, Cancel, Preview config (modal showing `ConfigPreview` JSON), Duplicate (edit mode only), Delete (edit mode only)

- [ ] **Step 2:** Use existing hooks (`useDockerfiles`, `useRoles`, `useMCPCatalog`, `useSkillsCatalog`) to feed dropdowns.

- [ ] **Step 3:** Preview modal: button triggers `configPreview(id)` and displays the returned `ConfigPreview` in a `<pre>` tag — nothing fancy, just the JSON dump and a list of `validation_errors` at the top.

- [ ] **Step 4:** TS strict + frontend test suite must stay green:
  ```bash
  cd /e/srcs/agflow.docker/frontend && npx tsc --noEmit && npm test
  ```

- [ ] **Step 5:** Commit:
  ```bash
  git add frontend/src/pages/AgentEditorPage.tsx
  git commit -m "feat(m4): AgentEditorPage form with all sections + config preview modal"
  ```

---

### Task 9: Wire router + nav

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/pages/HomePage.tsx`

- [ ] **Step 1:** Add 3 routes in `App.tsx`: `/agents`, `/agents/new`, `/agents/:id`.

- [ ] **Step 2:** Add nav link `Agents` on `HomePage.tsx` alongside the existing 6 links.

- [ ] **Step 3:** Run `tsc --noEmit` + `npm test` + full backend suite.

- [ ] **Step 4:** Commit:
  ```bash
  git add frontend/src/App.tsx frontend/src/pages/HomePage.tsx
  git commit -m "feat(m4): wire /agents routes + nav link"
  ```

---

### Task 10: Deploy + smoke test

- [ ] **Step 1:** `./scripts/deploy.sh --rebuild`

- [ ] **Step 2:** Apply migrations:
  ```bash
  ssh pve "pct exec 201 -- docker exec agflow-backend python -m agflow.db.migrations"
  ```
  Expected: `applied=['013_agents','014_agent_mcp_servers','015_agent_skills']`.

- [ ] **Step 3:** Unauth smoke test (401 = route mounted):
  ```bash
  curl -s -o /dev/null -w "%{http_code}\n" http://192.168.10.82/api/admin/agents
  ```
  Expected: `401`.

- [ ] **Step 4:** Check backend logs are clean:
  ```bash
  ssh pve "pct exec 201 -- docker logs agflow-backend --tail 20"
  ```

- [ ] **Step 5:** Report status. Do NOT push to GitHub without explicit approval.

---

## Verification end-to-end

```bash
cd /e/srcs/agflow.docker/backend  && uv run pytest -q          # target ~120 tests
cd /e/srcs/agflow.docker/backend  && uv run ruff check src/ tests/
cd /e/srcs/agflow.docker/frontend && npm test                  # target ~48 tests
cd /e/srcs/agflow.docker/frontend && npx tsc --noEmit
```

Browser walkthrough: login → `/agents` → Create → fill form (pick existing dockerfile + role + 1-2 MCPs + 1 skill) → Save → Preview config → inspect JSON → Duplicate → Delete.

---

## Self-Review Checklist

**Spec coverage (M4, 5a scope):**
- ✅ Agent structure (slug/name, 1 Dockerfile, 1 Role, N MCPs with overrides, N Skills)
- ✅ Lifecycle params
- ✅ Construction du répertoire (preview JSON only, no disk write)
- ✅ Image freshness indicator 🔴🟠🟢
- ✅ Duplication
- ✅ Actions (Create / Edit / Duplicate / Delete)
- ✅ Per-MCP parameters_override
- ⚠ **Builder visuel** — deferred to 5b (explicit non-goal)
- ⚠ **Session de test** — deferred to Phase 8
- ⚠ **Personnalisation mission** — deferred
- ⚠ **Communication inter-agents / Tools normalisés** — Phases 6/7

**Type consistency:** backend `AgentDetail` ↔ frontend `AgentDetail` interface — same field names and order. `ConfigPreview` backend ↔ frontend. `ImageStatus` literal values identical across stacks.

**Placeholder scan:** Every task has exact file paths, SQL DDL, code anchors, and commands. No "TODO" / "TBD".

---

## Execution Handoff

Ready to execute inline. Recommended: stop after Task 5 (backend complete) to run a first checkpoint before starting the frontend tasks.
