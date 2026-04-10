# agflow.docker Phase 4 — Module 3 (Catalogues MCP + Skills) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Module 3 — registries configuration (3a), MCP catalog (3b), Skills catalog (3c). End state: an admin can register `mcp.yoops.org`, test it (🟢 status based on the `YOOPS_API_KEY` secret), search for MCPs via a modal, add one to the local catalog, configure its parameters, do the same for skills. Module 3d (global MCP instantiation lifecycle) is **explicitly deferred**.

**Architecture:** 3 new tables (`discovery_services`, `mcp_servers`, `skills`). A generic `discovery_client.py` performs HTTP calls to registry APIs with Bearer/X-API-Key auth sourced from Module 0. The admin router exposes CRUD + proxied search endpoints. Frontend is 3 separate pages (one per 3a/3b/3c), each with React Query hooks, using the existing `StatusIndicator` component for 🔴🟠🟢 badges on API key status.

**Tech Stack:** Backend — httpx async, asyncpg, FastAPI, pytest. Frontend — React 18 + TS strict, React Query, i18next.

---

## Context

Phase 0-3 gave us the platform shell + Secrets + Roles + Dockerfiles. Module 3 is where the system starts aggregating **external knowledge**: MCP servers from registries like `mcp.yoops.org` (tools the agents will use later in M4) and Skills packs (reusable behavior files attached to agents). Without M3, an agent in M4 has nothing to hook into except its own Dockerfile and role.

**What is NOT in this phase:**
- **3d — Global MCP instantiation** — running MCP containers as shared services, health checks, lifecycle management. This is a significant amount of aiodocker work and will become its own phase (probably combined with M4 or right after). Phase 4 only stores metadata.
- **Real semantic search with vector DB** — the modal has a "Sémantique" checkbox but it just passes `semantic=1` as a query param to the registry. The registry is responsible for vector search; we're a dumb proxy.
- **Auto-sync from registries** — no background job that periodically refreshes the catalog. Each "add from search" is a manual user action.
- **Multi-registry aggregation** — if the user configures 2 registries, each registry's catalog is independent; no cross-registry merging or deduplication.

### Assumed registry API shape

Since the `mcp.yoops.org` API schema isn't hard-coded in this plan (it's a real prod service we don't fully know the shape of), the `discovery_client` uses **minimal, adaptable** calls. If the real API differs, only `discovery_client.py` needs adjusting — the rest of the plan holds.

**Assumed endpoints** (to confirm against real yoops API before executing):
- `GET {base_url}/health` → 200 OK for connectivity test
- `GET {base_url}/mcp/search?q={query}&semantic={0|1}` → `{ "items": [MCPSearchResult] }`
- `GET {base_url}/mcp/{package_id}` → `MCPDetail`
- `GET {base_url}/skills/search?q={query}` → `{ "items": [SkillSearchResult] }`
- `GET {base_url}/skills/{skill_id}` → `SkillDetail`
- Auth: `Authorization: Bearer <api_key>` from the configured secret

**Assumed `MCPDetail` shape:**
```json
{
  "package_id": "@modelcontextprotocol/server-filesystem",
  "name": "Filesystem",
  "repo": "modelcontextprotocol/servers",
  "repo_url": "https://github.com/modelcontextprotocol/servers",
  "transport": "stdio",
  "short_description": "...",
  "long_description": "...",
  "documentation_url": "https://...",
  "parameters_schema": [
    {"name": "ROOT_PATH", "description": "...", "is_secret": false, "required": true}
  ]
}
```

**Assumed `SkillDetail` shape:**
```json
{
  "skill_id": "markdown-editing",
  "name": "Markdown Editing",
  "description": "Best practices for editing markdown documents",
  "content_md": "# SKILL.md content..."
}
```

The plan ships a **mock mode** for the discovery client (`AGFLOW_DISCOVERY_MOCK=1` env var) so tests and smoke tests can run without hitting the real yoops API. The mock returns canned fixtures from `backend/tests/fixtures/yoops_*.json`.

---

## File Structure

### Backend — created
- `backend/migrations/010_discovery_services.sql`
- `backend/migrations/011_mcp_servers.sql`
- `backend/migrations/012_skills.sql`
- `backend/src/agflow/schemas/catalogs.py`
- `backend/src/agflow/services/discovery_services_service.py`
- `backend/src/agflow/services/discovery_client.py`
- `backend/src/agflow/services/mcp_catalog_service.py`
- `backend/src/agflow/services/skills_catalog_service.py`
- `backend/src/agflow/api/admin/discovery_services.py`
- `backend/src/agflow/api/admin/mcp_catalog.py`
- `backend/src/agflow/api/admin/skills_catalog.py`
- `backend/tests/test_discovery_services_service.py`
- `backend/tests/test_discovery_client.py`
- `backend/tests/test_mcp_catalog_service.py`
- `backend/tests/test_catalogs_endpoint.py`

### Backend — modified
- `backend/src/agflow/main.py` — register 3 routers

### Frontend — created
- `frontend/src/lib/discoveryApi.ts`
- `frontend/src/lib/mcpCatalogApi.ts`
- `frontend/src/lib/skillsCatalogApi.ts`
- `frontend/src/hooks/useDiscoveryServices.ts`
- `frontend/src/hooks/useMCPCatalog.ts`
- `frontend/src/hooks/useSkillsCatalog.ts`
- `frontend/src/components/SearchModal.tsx`
- `frontend/src/pages/DiscoveryServicesPage.tsx`
- `frontend/src/pages/MCPCatalogPage.tsx`
- `frontend/src/pages/SkillsCatalogPage.tsx`
- `frontend/tests/hooks/useDiscoveryServices.test.tsx`
- `frontend/tests/pages/DiscoveryServicesPage.test.tsx`

### Frontend — modified
- `frontend/src/App.tsx` — 3 new routes
- `frontend/src/pages/HomePage.tsx` — 3 new nav links
- `frontend/src/i18n/fr.json` + `en.json` — discovery + mcp_catalog + skills_catalog sections

---

## Data model

### `discovery_services` (010)

```sql
CREATE TABLE IF NOT EXISTS discovery_services (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    base_url        TEXT NOT NULL,
    api_key_var     TEXT NULL,
    description     TEXT NOT NULL DEFAULT '',
    enabled         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

`id` = slug (ex: `yoops`). `api_key_var` = env var name (ex: `YOOPS_API_KEY`), **never** the value. Value is resolved at call time from Module 0 secrets via `secrets_service.resolve_env([api_key_var])`.

### `mcp_servers` (011)

```sql
CREATE TABLE IF NOT EXISTS mcp_servers (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    discovery_service_id TEXT NOT NULL REFERENCES discovery_services(id) ON DELETE CASCADE,
    package_id        TEXT NOT NULL,
    name              TEXT NOT NULL,
    repo              TEXT NOT NULL DEFAULT '',
    repo_url          TEXT NOT NULL DEFAULT '',
    transport         TEXT NOT NULL DEFAULT 'stdio'
                      CHECK (transport IN ('stdio', 'sse', 'docker')),
    short_description TEXT NOT NULL DEFAULT '',
    long_description  TEXT NOT NULL DEFAULT '',
    documentation_url TEXT NOT NULL DEFAULT '',
    parameters        JSONB NOT NULL DEFAULT '{}'::jsonb,
    parameters_schema JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (discovery_service_id, package_id)
);

CREATE INDEX IF NOT EXISTS idx_mcp_servers_repo ON mcp_servers(repo);
```

### `skills` (012)

```sql
CREATE TABLE IF NOT EXISTS skills (
    id                   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    discovery_service_id TEXT NOT NULL REFERENCES discovery_services(id) ON DELETE CASCADE,
    skill_id             TEXT NOT NULL,
    name                 TEXT NOT NULL,
    description          TEXT NOT NULL DEFAULT '',
    content_md           TEXT NOT NULL DEFAULT '',
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (discovery_service_id, skill_id)
);
```

### API shape

| Endpoint | Method | Body / Params | Returns |
|---|---|---|---|
| `/api/admin/discovery-services` | GET | — | `list[DiscoveryServiceSummary]` |
| `/api/admin/discovery-services` | POST | `DiscoveryServiceCreate` | `DiscoveryServiceSummary` |
| `/api/admin/discovery-services/{id}` | PUT | `DiscoveryServiceUpdate` | `DiscoveryServiceSummary` |
| `/api/admin/discovery-services/{id}` | DELETE | — | 204 |
| `/api/admin/discovery-services/{id}/test` | POST | — | `{ok: bool, detail: str}` |
| `/api/admin/discovery-services/{id}/search/mcp` | GET | `?q=...&semantic=0/1` | `list[MCPSearchItem]` |
| `/api/admin/discovery-services/{id}/search/skills` | GET | `?q=...` | `list[SkillSearchItem]` |
| `/api/admin/mcp-catalog` | GET | — | `list[MCPServerSummary]` |
| `/api/admin/mcp-catalog` | POST | `MCPInstallPayload {discovery_service_id, package_id}` | `MCPServerSummary` |
| `/api/admin/mcp-catalog/{id}` | PUT | `{parameters}` | `MCPServerSummary` |
| `/api/admin/mcp-catalog/{id}` | DELETE | — | 204 |
| `/api/admin/skills-catalog` | GET | — | `list[SkillSummary]` |
| `/api/admin/skills-catalog` | POST | `SkillInstallPayload {discovery_service_id, skill_id}` | `SkillSummary` |
| `/api/admin/skills-catalog/{id}` | DELETE | — | 204 |

---

## Tasks

### Task 1: Migrations 010, 011, 012

- [ ] **Step 1: Write the 3 SQL files** (see "Data model" section)

- [ ] **Step 2: Append test to `test_migrations.py`**

```python
@pytest.mark.asyncio
async def test_migrations_010_011_012_create_catalogs_tables() -> None:
    for t in ["skills", "mcp_servers", "discovery_services",
              "dockerfile_builds", "dockerfile_files", "dockerfiles",
              "role_documents", "roles", "secrets", "schema_migrations"]:
        await execute(f"DROP TABLE IF EXISTS {t} CASCADE")

    applied = await run_migrations(_MIGRATIONS_DIR)

    assert "010_discovery_services" in applied
    assert "011_mcp_servers" in applied
    assert "012_skills" in applied

    rows = await fetch_all(
        """
        SELECT table_name FROM information_schema.tables
        WHERE table_name IN ('discovery_services', 'mcp_servers', 'skills')
        ORDER BY table_name
        """
    )
    assert [r["table_name"] for r in rows] == ["discovery_services", "mcp_servers", "skills"]
    await close_pool()
```

- [ ] **Step 3: Run migrations test**

Run: `cd backend && uv run python -m pytest tests/test_migrations.py -v`
Expected: 6 tests pass.

- [ ] **Step 4: Commit**

```bash
git add backend/migrations/010_*.sql backend/migrations/011_*.sql backend/migrations/012_*.sql backend/tests/test_migrations.py
git commit -m "feat(m3): migrations 010 + 011 + 012 for discovery/catalogs"
```

---

### Task 2: Pydantic schemas

Create `backend/src/agflow/schemas/catalogs.py` with:
- `DiscoveryServiceCreate/Update/Summary`
- `MCPInstallPayload`, `MCPServerSummary`, `MCPSearchItem`
- `SkillInstallPayload`, `SkillSummary`, `SkillSearchItem`
- `TestResult` (`ok: bool`, `detail: str`)

All with slug validator on ids, transport Literal, etc. Commit.

---

### Task 3: `discovery_client.py` (TDD with httpx MockTransport)

Generic HTTP client with methods:
- `probe(base_url, api_key) -> bool` — `GET /health`, timeout 5s
- `search_mcp(base_url, api_key, query, semantic) -> list[dict]`
- `search_skills(base_url, api_key, query) -> list[dict]`
- `get_mcp_detail(base_url, api_key, package_id) -> dict`
- `get_skill_detail(base_url, api_key, skill_id) -> dict`

Tests use `httpx.MockTransport` to simulate responses. Commit.

---

### Task 4: `discovery_services_service.py` CRUD (TDD)

Classic CRUD: create/list/get/update/delete + `test_connectivity(id)` which resolves the api key from Module 0, calls `discovery_client.probe`, returns `{ok, detail}`. Commit.

---

### Task 5: `mcp_catalog_service.py` (TDD)

- `list_all()`
- `install(discovery_service_id, package_id)` — fetches `get_mcp_detail` from the registry, stores it locally
- `update_parameters(id, params)`
- `delete(id)`

Tests mock `discovery_client.get_mcp_detail` to return canned fixtures.

---

### Task 6: `skills_catalog_service.py` (TDD)

Same pattern as MCP:
- `list_all()`
- `install(discovery_service_id, skill_id)` — fetches `get_skill_detail`, stores
- `delete(id)`

---

### Task 7: Admin router + endpoint tests

Three sub-routers in `api/admin/`:
- `discovery_services.py` — 6 endpoints
- `mcp_catalog.py` — 4 endpoints
- `skills_catalog.py` — 3 endpoints

One integration test file `test_catalogs_endpoint.py` covering happy paths for each router. Register in `main.py`. Commit.

---

### Task 8: Frontend i18n + 3 API clients

Add `discovery`, `mcp_catalog`, `skills_catalog` sections to `fr.json` and `en.json`. Create 3 typed axios wrappers in `frontend/src/lib/`. TS check + commit.

---

### Task 9: 3 React Query hooks

`useDiscoveryServices`, `useMCPCatalog`, `useSkillsCatalog` — standard list + mutations pattern. One test file for `useDiscoveryServices` (2 tests). Commit.

---

### Task 10: `SearchModal` component (reusable)

Generic search modal with `onSearch`, `onSelect`, children render function. Used by both MCP and Skills catalog pages. No specific test — exercised via page tests.

---

### Task 11: `DiscoveryServicesPage` — table + test + route

Table with columns: name, base_url, api_key_var (with StatusIndicator), actions (edit/delete/test). Click "Test" → calls `POST /test` → shows ✅ or ❌. Plus "+ Add" button with modal form. 2 tests. Commit.

---

### Task 12: `MCPCatalogPage` — grouped list + search modal + install

List of installed MCPs grouped by `repo` with headers. Each MCP row: name (bold), package_id, transport badge, actions (configure/delete). Top right: dropdown of discovery services + "Search MCPs" button → opens `SearchModal`. Click "Add" in the modal → calls backend install endpoint. Commit.

---

### Task 13: `SkillsCatalogPage` — flat list + search modal + install

Same pattern as MCP but flat (no grouping by repo). Commit.

---

### Task 14: Deploy + smoke test

1. Rebuild + deploy
2. Apply migrations
3. Create discovery service `yoops` with base_url `https://mcp.yoops.org/api/v1` and api_key_var `YOOPS_API_KEY`
4. Create the secret `YOOPS_API_KEY` in Module 0 (if the real key is known)
5. Click "Test" → if the real API responds, 🟢; otherwise document the expected shape mismatch for later adjustment
6. If test passes, search for "filesystem" → install the first result → verify row appears in catalog
7. Browser walkthrough of the 3 new pages
8. Final push

---

## Verification end-to-end

```bash
cd backend && uv run python -m pytest -q        # ~105 backend tests
cd backend && uv run ruff check src/ tests/
cd frontend && npm test                          # ~45 frontend tests
cd frontend && npx tsc --noEmit
```

Browser: login → /discovery-services → add yoops → test → /mcp-catalog → search → add one → /skills-catalog → search → add one.

---

## Self-Review Checklist

**Spec coverage (M3):**
- ✅ 3a Registries CRUD + test + multi-registry
- ✅ 3a 🔴🟠🟢 indicators on api_key_var
- ✅ 3b MCP catalog grouped by repo
- ✅ 3b Search modal with sémantique checkbox
- ✅ 3b Transport badge (stdio/sse/docker)
- ✅ 3b Per-MCP parameters editable
- ✅ 3c Skills catalog with same search pattern
- ⚠ **3d Global MCP instantiation** — explicit non-goal
- ⚠ **Semantic search real implementation** — just a query param passed to the registry

**Type consistency:** backend schemas ↔ frontend interfaces named identically (`DiscoveryServiceSummary`, `MCPServerSummary`, `SkillSummary`).

---

## Execution Handoff

Ready to execute inline. Before running, you may want to confirm the assumed yoops API shape. If it differs from the assumptions, only `discovery_client.py` needs to be adjusted — all other layers (service, router, frontend) are registry-agnostic.
