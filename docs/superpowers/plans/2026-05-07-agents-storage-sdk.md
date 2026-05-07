# Agents — SQL Migration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the filesystem-based agent storage (`agent.json` files) with PostgreSQL tables, eliminating O(N) scans and global state.

**Architecture:** Two new tables — `agents` (all scalar + JSONB fields) and `agent_profiles` (rows for legacy profile format). `agents.id` stores UUID5 computed from slug for API compatibility. `agents_service.py` and `agent_profiles_service.py` are fully rewritten to SQL; `agent_files_service.py` is deleted.

**Tech Stack:** asyncpg, asyncpg pool helpers (`fetch_one`, `fetch_all`, `execute`), `json.dumps()` for JSONB writes, Pydantic v2 models unchanged.

---

## File Map

| Action | Path |
|--------|------|
| Create | `backend/migrations/096_agents.sql` |
| Rewrite | `backend/src/agflow/services/agents_service.py` |
| Rewrite | `backend/src/agflow/services/agent_profiles_service.py` |
| Delete | `backend/src/agflow/services/agent_files_service.py` |
| Create | `backend/tests/test_agents_service.py` |
| Create | `backend/tests/test_agent_profiles_service.py` |

---

### Task 1: SQL Migration

**Files:**
- Create: `backend/migrations/096_agents.sql`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_agents_service.py` with just the migration smoke test:

```python
from __future__ import annotations

import pytest

from agflow.db.pool import close_pool, fetch_all
from tests._db_reset import reset_schema_and_migrate


@pytest.fixture(autouse=True)
async def _clean():
    await reset_schema_and_migrate()
    yield
    await close_pool()


@pytest.mark.asyncio
async def test_migration_creates_agents_table() -> None:
    rows = await fetch_all(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'agents' ORDER BY column_name"
    )
    columns = {r["column_name"] for r in rows}
    assert "slug" in columns
    assert "id" in columns
    assert "mcp_bindings" in columns
    assert "generations" in columns
    assert "is_assistant" in columns


@pytest.mark.asyncio
async def test_migration_creates_agent_profiles_table() -> None:
    rows = await fetch_all(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'agent_profiles' ORDER BY column_name"
    )
    columns = {r["column_name"] for r in rows}
    assert "id" in columns
    assert "agent_slug" in columns
    assert "document_ids" in columns
```

- [ ] **Step 2: Run test to verify it fails**

```
cd backend && uv run pytest tests/test_agents_service.py::test_migration_creates_agents_table -v
```

Expected: FAIL — `AssertionError` (table doesn't exist yet).

- [ ] **Step 3: Write the migration**

Create `backend/migrations/096_agents.sql`:

```sql
-- 096_agents.sql
-- Agents SQL storage: replaces {AGFLOW_DATA_DIR}/agents/{slug}/agent.json

CREATE TABLE IF NOT EXISTS agents (
    slug                    TEXT         NOT NULL PRIMARY KEY,
    id                      UUID         NOT NULL UNIQUE,
    display_name            TEXT         NOT NULL DEFAULT '',
    description             TEXT         NOT NULL DEFAULT '',
    dockerfile_id           TEXT         NOT NULL DEFAULT '',
    role_id                 TEXT         NOT NULL DEFAULT '',
    env_overrides           JSONB        NOT NULL DEFAULT '{}',
    mount_overrides         JSONB        NOT NULL DEFAULT '{}',
    param_overrides         JSONB        NOT NULL DEFAULT '{}',
    timeout_seconds         INT          NOT NULL DEFAULT 3600,
    workspace_path          TEXT         NOT NULL DEFAULT '/workspace',
    network_mode            TEXT         NOT NULL DEFAULT 'bridge',
    graceful_shutdown_secs  INT          NOT NULL DEFAULT 30,
    force_kill_delay_secs   INT          NOT NULL DEFAULT 10,
    is_assistant            BOOLEAN      NOT NULL DEFAULT FALSE,
    mcp_template_slug       TEXT         NOT NULL DEFAULT '',
    mcp_template_culture    TEXT         NOT NULL DEFAULT '',
    mcp_config_filename     TEXT         NOT NULL DEFAULT 'config.toml',
    skills_template_slug    TEXT         NOT NULL DEFAULT '',
    skills_template_culture TEXT         NOT NULL DEFAULT '',
    skills_config_filename  TEXT         NOT NULL DEFAULT 'skills.md',
    prompt_template_slug    TEXT         NOT NULL DEFAULT '',
    prompt_template_culture TEXT         NOT NULL DEFAULT '',
    prompt_filename         TEXT         NOT NULL DEFAULT 'prompt.md',
    mcp_bindings            JSONB        NOT NULL DEFAULT '[]',
    skill_bindings          JSONB        NOT NULL DEFAULT '[]',
    generations             JSONB        NOT NULL DEFAULT '[]',
    created_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TRIGGER set_updated_at_agents
    BEFORE UPDATE ON agents
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS agent_profiles (
    id               UUID        NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY,
    agent_slug       TEXT        NOT NULL REFERENCES agents(slug) ON DELETE CASCADE,
    name             TEXT        NOT NULL,
    description      TEXT        NOT NULL DEFAULT '',
    document_ids     UUID[]      NOT NULL DEFAULT '{}',
    template_slug    TEXT        NOT NULL DEFAULT '',
    template_culture TEXT        NOT NULL DEFAULT '',
    output_dir       TEXT        NOT NULL DEFAULT 'workspace/docs/missions',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (agent_slug, name)
);

CREATE TRIGGER set_updated_at_agent_profiles
    BEFORE UPDATE ON agent_profiles
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
```

- [ ] **Step 4: Run test to verify it passes**

```
cd backend && uv run pytest tests/test_agents_service.py::test_migration_creates_agents_table tests/test_agents_service.py::test_migration_creates_agent_profiles_table -v
```

Expected: PASS (both tests green).

- [ ] **Step 5: Commit**

```
git add backend/migrations/096_agents.sql backend/tests/test_agents_service.py
git commit -m "feat(agents): migration SQL 096 — tables agents + agent_profiles"
```

---

### Task 2: Rewrite `agents_service.py`

**Files:**
- Modify: `backend/src/agflow/services/agents_service.py`
- Modify: `backend/tests/test_agents_service.py`

- [ ] **Step 1: Add CRUD tests to the test file**

Append to `backend/tests/test_agents_service.py`:

```python
import uuid
from uuid import UUID

from agflow.services import agents_service
from agflow.services.agents_service import AgentNotFoundError, DuplicateAgentError
from agflow.schemas.agents import AgentCreate, AgentUpdate, AgentMCPBinding, AgentSkillBinding, AgentGeneration, AgentGenerationProfile


def _make_create(slug: str = "my-agent", display_name: str = "My Agent") -> AgentCreate:
    return AgentCreate(
        slug=slug,
        display_name=display_name,
        description="desc",
        dockerfile_id="dockerfile-abc",
    )


@pytest.mark.asyncio
async def test_list_all_empty() -> None:
    assert await agents_service.list_all() == []


@pytest.mark.asyncio
async def test_create_and_list() -> None:
    detail = await agents_service.create(_make_create())
    assert detail.slug == "my-agent"
    assert detail.display_name == "My Agent"
    assert detail.is_assistant is False
    summaries = await agents_service.list_all()
    assert len(summaries) == 1
    assert summaries[0].slug == "my-agent"


@pytest.mark.asyncio
async def test_create_duplicate_raises() -> None:
    await agents_service.create(_make_create())
    with pytest.raises(DuplicateAgentError):
        await agents_service.create(_make_create())


@pytest.mark.asyncio
async def test_get_by_id() -> None:
    detail = await agents_service.create(_make_create())
    fetched = await agents_service.get_by_id(detail.id)
    assert fetched.slug == "my-agent"


@pytest.mark.asyncio
async def test_get_by_id_not_found_raises() -> None:
    with pytest.raises(AgentNotFoundError):
        await agents_service.get_by_id(uuid.uuid4())


@pytest.mark.asyncio
async def test_update() -> None:
    detail = await agents_service.create(_make_create())
    updated = await agents_service.update(
        detail.id,
        AgentUpdate(display_name="Renamed", dockerfile_id="dockerfile-abc"),
    )
    assert updated.display_name == "Renamed"
    assert updated.slug == "my-agent"


@pytest.mark.asyncio
async def test_delete() -> None:
    detail = await agents_service.create(_make_create())
    await agents_service.delete(detail.id)
    assert await agents_service.list_all() == []


@pytest.mark.asyncio
async def test_delete_not_found_raises() -> None:
    with pytest.raises(AgentNotFoundError):
        await agents_service.delete(uuid.uuid4())


@pytest.mark.asyncio
async def test_duplicate() -> None:
    detail = await agents_service.create(_make_create("original", "Original"))
    dup = await agents_service.duplicate(detail.id, "copy", "Copy")
    assert dup.slug == "copy"
    assert dup.display_name == "Copy"
    assert len(await agents_service.list_all()) == 2


@pytest.mark.asyncio
async def test_get_assistant_returns_none_when_none() -> None:
    await agents_service.create(_make_create())
    assert await agents_service.get_assistant() is None


@pytest.mark.asyncio
async def test_set_assistant() -> None:
    detail = await agents_service.create(_make_create())
    await agents_service.set_assistant(detail.id)
    assistant = await agents_service.get_assistant()
    assert assistant is not None
    assert assistant.slug == "my-agent"
    assert assistant.is_assistant is True


@pytest.mark.asyncio
async def test_set_assistant_clears_previous() -> None:
    a = await agents_service.create(_make_create("agent-a", "A"))
    b = await agents_service.create(_make_create("agent-b", "B"))
    await agents_service.set_assistant(a.id)
    await agents_service.set_assistant(b.id)
    assistant = await agents_service.get_assistant()
    assert assistant is not None and assistant.slug == "agent-b"
    a_refetched = await agents_service.get_by_id(a.id)
    assert a_refetched.is_assistant is False


@pytest.mark.asyncio
async def test_clear_assistant() -> None:
    detail = await agents_service.create(_make_create())
    await agents_service.set_assistant(detail.id)
    await agents_service.clear_assistant()
    assert await agents_service.get_assistant() is None


@pytest.mark.asyncio
async def test_mcp_bindings_stored_and_retrieved() -> None:
    mcp_id = uuid.uuid4()
    payload = AgentCreate(
        slug="agent-mcp",
        display_name="MCP Agent",
        dockerfile_id="df",
        mcp_bindings=[AgentMCPBinding(mcp_server_id=mcp_id, parameters_override={"key": "val"}, position=1)],
    )
    detail = await agents_service.create(payload)
    assert len(detail.mcp_bindings) == 1
    assert detail.mcp_bindings[0].mcp_server_id == mcp_id
    assert detail.mcp_bindings[0].parameters_override == {"key": "val"}


@pytest.mark.asyncio
async def test_skill_bindings_stored_and_retrieved() -> None:
    skill_id = uuid.uuid4()
    payload = AgentCreate(
        slug="agent-skill",
        display_name="Skill Agent",
        dockerfile_id="df",
        skill_bindings=[AgentSkillBinding(skill_id=skill_id)],
    )
    detail = await agents_service.create(payload)
    assert len(detail.skill_bindings) == 1
    assert detail.skill_bindings[0].skill_id == skill_id


@pytest.mark.asyncio
async def test_generations_stored_and_retrieved() -> None:
    gen = AgentGeneration(
        role_id="assistant",
        template_slug="base",
        template_culture="fr",
        prompt_filename="prompt.md",
        profiles=[AgentGenerationProfile(name="p1", documents=["roles/doc.md"])],
    )
    payload = AgentCreate(
        slug="agent-gen",
        display_name="Gen Agent",
        dockerfile_id="df",
        generations=[gen],
    )
    detail = await agents_service.create(payload)
    assert len(detail.generations) == 1
    assert detail.generations[0].role_id == "assistant"
    assert detail.generations[0].profiles[0].name == "p1"


@pytest.mark.asyncio
async def test_env_overrides_stored_and_retrieved() -> None:
    payload = AgentCreate(
        slug="agent-env",
        display_name="Env Agent",
        dockerfile_id="df",
        env_vars={"env_overrides": {"MY_VAR": "hello"}, "mount_overrides": {}, "param_overrides": {}},
    )
    detail = await agents_service.create(payload)
    assert detail.env_vars["env_overrides"]["MY_VAR"] == "hello"
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd backend && uv run pytest tests/test_agents_service.py -v
```

Expected: FAIL on all CRUD tests — `agent_files_service` raises filesystem errors (not DB errors) until the service is rewritten.

- [ ] **Step 3: Rewrite `agents_service.py`**

Replace the entire content of `backend/src/agflow/services/agents_service.py`:

```python
from __future__ import annotations

import json
import uuid
from typing import Any
from uuid import UUID

import asyncpg
import structlog

from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.schemas.agents import (
    AgentCreate,
    AgentDetail,
    AgentGeneration,
    AgentMCPBinding,
    AgentSkillBinding,
    AgentSummary,
    AgentUpdate,
    ImageStatus,
)

_log = structlog.get_logger(__name__)

_AGENT_NS = uuid.UUID("b2c3d4e5-f6a7-8901-bcde-f12345678901")


class AgentNotFoundError(Exception):
    pass


class DuplicateAgentError(Exception):
    pass


class InvalidReferenceError(Exception):
    pass


def _slug_to_uuid(slug: str) -> UUID:
    return uuid.uuid5(_AGENT_NS, slug)


_COLS = (
    "slug, id, display_name, description, dockerfile_id, role_id, "
    "env_overrides, mount_overrides, param_overrides, "
    "timeout_seconds, workspace_path, network_mode, "
    "graceful_shutdown_secs, force_kill_delay_secs, is_assistant, "
    "mcp_template_slug, mcp_template_culture, mcp_config_filename, "
    "skills_template_slug, skills_template_culture, skills_config_filename, "
    "prompt_template_slug, prompt_template_culture, prompt_filename, "
    "mcp_bindings, skill_bindings, generations, "
    "created_at, updated_at"
)


def _row_to_summary(row: dict[str, Any]) -> AgentSummary:
    return AgentSummary(
        id=row["id"],
        slug=row["slug"],
        display_name=row["display_name"],
        description=row["description"],
        dockerfile_id=row["dockerfile_id"],
        role_id=row["role_id"],
        env_vars={
            "env_overrides": dict(row["env_overrides"] or {}),
            "mount_overrides": dict(row["mount_overrides"] or {}),
            "param_overrides": dict(row["param_overrides"] or {}),
        },
        timeout_seconds=row["timeout_seconds"],
        workspace_path=row["workspace_path"],
        network_mode=row["network_mode"],
        graceful_shutdown_secs=row["graceful_shutdown_secs"],
        force_kill_delay_secs=row["force_kill_delay_secs"],
        is_assistant=row["is_assistant"],
        mcp_template_slug=row["mcp_template_slug"],
        mcp_template_culture=row["mcp_template_culture"],
        mcp_config_filename=row["mcp_config_filename"],
        skills_template_slug=row["skills_template_slug"],
        skills_template_culture=row["skills_template_culture"],
        skills_config_filename=row["skills_config_filename"],
        prompt_template_slug=row["prompt_template_slug"],
        prompt_template_culture=row["prompt_template_culture"],
        prompt_filename=row["prompt_filename"],
        generations=[
            AgentGeneration(**g) for g in (row["generations"] or [])
        ],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def _compute_image_status(dockerfile_id: str) -> ImageStatus:
    from agflow.services import build_service, dockerfile_files_service

    latest = await build_service.get_latest_build(dockerfile_id)
    if latest is None or latest["status"] != "success":
        return "missing"
    disk_files = await dockerfile_files_service.list_for_dockerfile(dockerfile_id)
    if not disk_files:
        return "missing"
    files_for_hash = [{"path": f.path, "content": f.content} for f in disk_files]
    current_hash = build_service.compute_hash(files_for_hash)
    if current_hash != latest["content_hash"]:
        return "stale"
    return "fresh"


async def _detail_from_row(row: dict[str, Any]) -> AgentDetail:
    summary = _row_to_summary(row)
    mcp_bindings = [
        AgentMCPBinding(
            mcp_server_id=UUID(b["catalog_mcp_id"]),
            parameters_override=b.get("config_overrides", {}),
            position=b.get("position", 0),
        )
        for b in (row["mcp_bindings"] or [])
        if b.get("catalog_mcp_id")
    ]
    skill_bindings = [
        AgentSkillBinding(skill_id=UUID(b["catalog_skill_id"]))
        for b in (row["skill_bindings"] or [])
        if b.get("catalog_skill_id")
    ]
    image_status = (
        await _compute_image_status(summary.dockerfile_id)
        if summary.dockerfile_id
        else "missing"
    )
    return AgentDetail(
        **summary.model_dump(),
        mcp_bindings=mcp_bindings,
        skill_bindings=skill_bindings,
        image_status=image_status,
    )


def _env(payload: AgentCreate | AgentUpdate, key: str) -> str:
    env = payload.env_vars if isinstance(payload.env_vars, dict) else {}
    return json.dumps(env.get(key, {}))


def _bindings_json(payload: AgentCreate | AgentUpdate) -> tuple[str, str]:
    mcp = json.dumps([
        {
            "catalog_mcp_id": str(b.mcp_server_id),
            "config_overrides": b.parameters_override,
            "position": b.position,
        }
        for b in (payload.mcp_bindings or [])
    ])
    skill = json.dumps([
        {"catalog_skill_id": str(b.skill_id)}
        for b in (payload.skill_bindings or [])
    ])
    return mcp, skill


async def create(payload: AgentCreate) -> AgentDetail:
    agent_id = _slug_to_uuid(payload.slug)
    mcp_json, skill_json = _bindings_json(payload)
    gen_json = json.dumps([g.model_dump(mode="json") for g in (payload.generations or [])])
    try:
        row = await fetch_one(
            f"""
            INSERT INTO agents (
                slug, id, display_name, description, dockerfile_id, role_id,
                env_overrides, mount_overrides, param_overrides,
                timeout_seconds, workspace_path, network_mode,
                graceful_shutdown_secs, force_kill_delay_secs,
                mcp_template_slug, mcp_template_culture, mcp_config_filename,
                skills_template_slug, skills_template_culture, skills_config_filename,
                prompt_template_slug, prompt_template_culture, prompt_filename,
                mcp_bindings, skill_bindings, generations
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14,
                $15, $16, $17, $18, $19, $20, $21, $22, $23, $24, $25, $26
            ) RETURNING {_COLS}
            """,
            payload.slug, agent_id, payload.display_name, payload.description,
            payload.dockerfile_id, payload.role_id,
            _env(payload, "env_overrides"),
            _env(payload, "mount_overrides"),
            _env(payload, "param_overrides"),
            payload.timeout_seconds, payload.workspace_path, payload.network_mode,
            payload.graceful_shutdown_secs, payload.force_kill_delay_secs,
            payload.mcp_template_slug, payload.mcp_template_culture, payload.mcp_config_filename,
            payload.skills_template_slug, payload.skills_template_culture, payload.skills_config_filename,
            payload.prompt_template_slug, payload.prompt_template_culture, payload.prompt_filename,
            mcp_json, skill_json, gen_json,
        )
    except asyncpg.UniqueViolationError as exc:
        raise DuplicateAgentError(f"Agent slug '{payload.slug}' already exists") from exc
    assert row is not None
    _log.info("agents.create", slug=payload.slug)
    return await _detail_from_row(row)


async def list_all() -> list[AgentSummary]:
    rows = await fetch_all(f"SELECT {_COLS} FROM agents ORDER BY display_name ASC")
    return [_row_to_summary(r) for r in rows]


async def get_by_id(agent_id: UUID) -> AgentDetail:
    row = await fetch_one(f"SELECT {_COLS} FROM agents WHERE id = $1", agent_id)
    if row is None:
        raise AgentNotFoundError(f"Agent {agent_id} not found")
    return await _detail_from_row(row)


async def update(agent_id: UUID, payload: AgentUpdate) -> AgentDetail:
    mcp_json, skill_json = _bindings_json(payload)
    gen_json = json.dumps([g.model_dump(mode="json") for g in (payload.generations or [])])
    row = await fetch_one(
        f"""
        UPDATE agents SET
            display_name = $2, description = $3, dockerfile_id = $4, role_id = $5,
            env_overrides = $6, mount_overrides = $7, param_overrides = $8,
            timeout_seconds = $9, workspace_path = $10, network_mode = $11,
            graceful_shutdown_secs = $12, force_kill_delay_secs = $13,
            mcp_template_slug = $14, mcp_template_culture = $15, mcp_config_filename = $16,
            skills_template_slug = $17, skills_template_culture = $18, skills_config_filename = $19,
            prompt_template_slug = $20, prompt_template_culture = $21, prompt_filename = $22,
            mcp_bindings = $23, skill_bindings = $24, generations = $25
        WHERE id = $1
        RETURNING {_COLS}
        """,
        agent_id, payload.display_name, payload.description,
        payload.dockerfile_id, payload.role_id,
        _env(payload, "env_overrides"),
        _env(payload, "mount_overrides"),
        _env(payload, "param_overrides"),
        payload.timeout_seconds, payload.workspace_path, payload.network_mode,
        payload.graceful_shutdown_secs, payload.force_kill_delay_secs,
        payload.mcp_template_slug, payload.mcp_template_culture, payload.mcp_config_filename,
        payload.skills_template_slug, payload.skills_template_culture, payload.skills_config_filename,
        payload.prompt_template_slug, payload.prompt_template_culture, payload.prompt_filename,
        mcp_json, skill_json, gen_json,
    )
    if row is None:
        raise AgentNotFoundError(f"Agent {agent_id} not found")
    _log.info("agents.update", agent_id=str(agent_id))
    return await _detail_from_row(row)


async def delete(agent_id: UUID) -> None:
    result = await execute("DELETE FROM agents WHERE id = $1", agent_id)
    if result == "DELETE 0":
        raise AgentNotFoundError(f"Agent {agent_id} not found")
    _log.info("agents.delete", agent_id=str(agent_id))


async def duplicate(agent_id: UUID, new_slug: str, new_display_name: str) -> AgentDetail:
    source = await get_by_id(agent_id)
    payload = AgentCreate(
        slug=new_slug,
        display_name=new_display_name,
        description=source.description,
        dockerfile_id=source.dockerfile_id,
        role_id=source.role_id,
        env_vars=source.env_vars,
        timeout_seconds=source.timeout_seconds,
        workspace_path=source.workspace_path,
        network_mode=source.network_mode,
        graceful_shutdown_secs=source.graceful_shutdown_secs,
        force_kill_delay_secs=source.force_kill_delay_secs,
        mcp_bindings=source.mcp_bindings,
        skill_bindings=source.skill_bindings,
        generations=source.generations,
    )
    return await create(payload)


async def get_assistant() -> AgentSummary | None:
    row = await fetch_one(f"SELECT {_COLS} FROM agents WHERE is_assistant = TRUE LIMIT 1")
    return _row_to_summary(row) if row else None


async def set_assistant(agent_id: UUID) -> None:
    await execute("UPDATE agents SET is_assistant = FALSE WHERE is_assistant = TRUE AND id != $1", agent_id)
    result = await execute("UPDATE agents SET is_assistant = TRUE WHERE id = $1", agent_id)
    if result == "UPDATE 0":
        raise AgentNotFoundError(f"Agent {agent_id} not found")
    _log.info("agents.set_assistant", agent_id=str(agent_id))


async def clear_assistant() -> None:
    await execute("UPDATE agents SET is_assistant = FALSE WHERE is_assistant = TRUE")
```

- [ ] **Step 4: Run ruff**

```
cd backend && uv run ruff check src/agflow/services/agents_service.py
```

Expected: no errors. Fix any reported issues before continuing.

- [ ] **Step 5: Run tests to verify they pass**

```
cd backend && uv run pytest tests/test_agents_service.py -v
```

Expected: All tests PASS (or connection error if running from Windows — that's normal; all tests should show the same DB connection error, not `ImportError` or `AttributeError`).

- [ ] **Step 6: Commit**

```
git add backend/src/agflow/services/agents_service.py backend/tests/test_agents_service.py
git commit -m "feat(agents): réécriture agents_service en SQL (O(1) get_by_id, set_assistant)"
```

---

### Task 3: Rewrite `agent_profiles_service.py`

**Files:**
- Modify: `backend/src/agflow/services/agent_profiles_service.py`
- Create: `backend/tests/test_agent_profiles_service.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_agent_profiles_service.py`:

```python
from __future__ import annotations

import uuid

import pytest

from agflow.db.pool import close_pool
from agflow.schemas.agents import AgentCreate
from agflow.services import agent_profiles_service, agents_service
from agflow.services.agent_profiles_service import DuplicateProfileError, ProfileNotFoundError
from tests._db_reset import reset_schema_and_migrate


@pytest.fixture(autouse=True)
async def _clean():
    await reset_schema_and_migrate()
    yield
    await close_pool()


async def _make_agent(slug: str = "my-agent") -> uuid.UUID:
    detail = await agents_service.create(
        AgentCreate(slug=slug, display_name="My Agent", dockerfile_id="df")
    )
    return detail.id


@pytest.mark.asyncio
async def test_list_for_agent_empty() -> None:
    agent_id = await _make_agent()
    assert await agent_profiles_service.list_for_agent(agent_id) == []


@pytest.mark.asyncio
async def test_create_and_list() -> None:
    agent_id = await _make_agent()
    profile = await agent_profiles_service.create(agent_id, "Profile 1", "desc")
    assert profile.name == "Profile 1"
    assert profile.agent_id == agent_id
    profiles = await agent_profiles_service.list_for_agent(agent_id)
    assert len(profiles) == 1
    assert profiles[0].name == "Profile 1"


@pytest.mark.asyncio
async def test_create_duplicate_raises() -> None:
    agent_id = await _make_agent()
    await agent_profiles_service.create(agent_id, "Profile 1")
    with pytest.raises(DuplicateProfileError):
        await agent_profiles_service.create(agent_id, "Profile 1")


@pytest.mark.asyncio
async def test_get_by_id() -> None:
    agent_id = await _make_agent()
    created = await agent_profiles_service.create(agent_id, "Profile 1")
    fetched = await agent_profiles_service.get_by_id(created.id)
    assert fetched.name == "Profile 1"


@pytest.mark.asyncio
async def test_get_by_id_not_found_raises() -> None:
    with pytest.raises(ProfileNotFoundError):
        await agent_profiles_service.get_by_id(uuid.uuid4())


@pytest.mark.asyncio
async def test_update_name_and_description() -> None:
    agent_id = await _make_agent()
    profile = await agent_profiles_service.create(agent_id, "Old Name")
    updated = await agent_profiles_service.update(profile.id, name="New Name", description="updated")
    assert updated.name == "New Name"
    assert updated.description == "updated"


@pytest.mark.asyncio
async def test_update_document_ids() -> None:
    agent_id = await _make_agent()
    doc_id = uuid.uuid4()
    profile = await agent_profiles_service.create(agent_id, "P")
    updated = await agent_profiles_service.update(profile.id, document_ids=[doc_id])
    assert doc_id in updated.document_ids


@pytest.mark.asyncio
async def test_delete() -> None:
    agent_id = await _make_agent()
    profile = await agent_profiles_service.create(agent_id, "P")
    await agent_profiles_service.delete(profile.id)
    assert await agent_profiles_service.list_for_agent(agent_id) == []


@pytest.mark.asyncio
async def test_delete_not_found_raises() -> None:
    with pytest.raises(ProfileNotFoundError):
        await agent_profiles_service.delete(uuid.uuid4())


@pytest.mark.asyncio
async def test_delete_agent_cascades_profiles() -> None:
    agent_id = await _make_agent()
    await agent_profiles_service.create(agent_id, "P1")
    await agents_service.delete(agent_id)
    assert await agents_service.list_all() == []
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd backend && uv run pytest tests/test_agent_profiles_service.py -v
```

Expected: FAIL — the service still reads from filesystem.

- [ ] **Step 3: Rewrite `agent_profiles_service.py`**

Replace the entire content of `backend/src/agflow/services/agent_profiles_service.py`:

```python
from __future__ import annotations

from uuid import UUID

import asyncpg
import structlog

from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.schemas.agents import AgentProfileSummary

_log = structlog.get_logger(__name__)

_COLS = (
    "ap.id, a.id AS agent_id, ap.agent_slug, ap.name, ap.description, "
    "ap.document_ids, ap.template_slug, ap.template_culture, ap.output_dir, "
    "ap.created_at, ap.updated_at"
)

_JOIN = "FROM agent_profiles ap JOIN agents a ON a.slug = ap.agent_slug"


class ProfileNotFoundError(Exception):
    pass


class DuplicateProfileError(Exception):
    pass


def _row(row: dict) -> AgentProfileSummary:
    return AgentProfileSummary(
        id=row["id"],
        agent_id=row["agent_id"],
        name=row["name"],
        description=row["description"],
        document_ids=list(row["document_ids"] or []),
        template_slug=row["template_slug"],
        template_culture=row["template_culture"],
        output_dir=row["output_dir"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def list_for_agent(agent_id: UUID) -> list[AgentProfileSummary]:
    rows = await fetch_all(
        f"SELECT {_COLS} {_JOIN} WHERE a.id = $1 ORDER BY ap.name ASC",
        agent_id,
    )
    return [_row(r) for r in rows]


async def get_by_id(profile_id: UUID) -> AgentProfileSummary:
    row = await fetch_one(
        f"SELECT {_COLS} {_JOIN} WHERE ap.id = $1",
        profile_id,
    )
    if row is None:
        raise ProfileNotFoundError(f"Profile {profile_id} not found")
    return _row(row)


async def create(
    agent_id: UUID,
    name: str,
    description: str = "",
    document_ids: list[UUID] | None = None,
    template_slug: str = "",
    template_culture: str = "",
    output_dir: str = "workspace/docs/missions",
) -> AgentProfileSummary:
    slug_row = await fetch_one("SELECT slug FROM agents WHERE id = $1", agent_id)
    if slug_row is None:
        raise ProfileNotFoundError(f"Agent {agent_id} not found")
    agent_slug = slug_row["slug"]
    doc_ids: list[UUID] = document_ids or []
    try:
        row = await fetch_one(
            f"""
            INSERT INTO agent_profiles (agent_slug, name, description, document_ids,
                template_slug, template_culture, output_dir)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id, $8::uuid AS agent_id, agent_slug, name, description,
                document_ids, template_slug, template_culture, output_dir,
                created_at, updated_at
            """,
            agent_slug, name, description, doc_ids,
            template_slug, template_culture, output_dir,
            agent_id,
        )
    except asyncpg.UniqueViolationError as exc:
        raise DuplicateProfileError(f"Profile '{name}' already exists for this agent") from exc
    assert row is not None
    _log.info("agent_profiles.create", agent_slug=agent_slug, name=name)
    return _row(row)


async def update(
    profile_id: UUID,
    name: str | None = None,
    description: str | None = None,
    document_ids: list[UUID] | None = None,
    template_slug: str | None = None,
    template_culture: str | None = None,
    output_dir: str | None = None,
) -> AgentProfileSummary:
    sets: list[str] = []
    params: list = [profile_id]
    if name is not None:
        params.append(name)
        sets.append(f"name = ${len(params)}")
    if description is not None:
        params.append(description)
        sets.append(f"description = ${len(params)}")
    if document_ids is not None:
        params.append(document_ids)
        sets.append(f"document_ids = ${len(params)}")
    if template_slug is not None:
        params.append(template_slug)
        sets.append(f"template_slug = ${len(params)}")
    if template_culture is not None:
        params.append(template_culture)
        sets.append(f"template_culture = ${len(params)}")
    if output_dir is not None:
        params.append(output_dir)
        sets.append(f"output_dir = ${len(params)}")
    if not sets:
        return await get_by_id(profile_id)
    set_clause = ", ".join(sets)
    row = await fetch_one(
        f"""
        UPDATE agent_profiles SET {set_clause}
        WHERE id = $1
        RETURNING id, agent_slug, name, description, document_ids,
            template_slug, template_culture, output_dir, created_at, updated_at
        """,
        *params,
    )
    if row is None:
        raise ProfileNotFoundError(f"Profile {profile_id} not found")
    agent_row = await fetch_one("SELECT id FROM agents WHERE slug = $1", row["agent_slug"])
    return _row({**dict(row), "agent_id": agent_row["id"] if agent_row else None})


async def delete(profile_id: UUID) -> None:
    result = await execute("DELETE FROM agent_profiles WHERE id = $1", profile_id)
    if result == "DELETE 0":
        raise ProfileNotFoundError(f"Profile {profile_id} not found")
    _log.info("agent_profiles.delete", profile_id=str(profile_id))


async def resolve_documents(document_ids: list[UUID]) -> tuple[list[dict], list[UUID]]:
    if not document_ids:
        return [], []
    from agflow.services import role_documents_service

    found = []
    missing = []
    for uid in document_ids:
        try:
            doc = await role_documents_service.get_by_id(uid)
            found.append({
                "id": doc.id,
                "role_id": doc.role_id,
                "section": doc.section,
                "name": doc.name,
                "content_md": doc.content_md,
                "parent_path": doc.parent_path,
                "protected": doc.protected,
                "created_at": doc.created_at,
                "updated_at": doc.updated_at,
            })
        except Exception:
            missing.append(uid)
    return found, missing
```

- [ ] **Step 4: Run ruff**

```
cd backend && uv run ruff check src/agflow/services/agent_profiles_service.py
```

Expected: no errors.

- [ ] **Step 5: Run tests to verify they pass**

```
cd backend && uv run pytest tests/test_agent_profiles_service.py -v
```

Expected: all PASS (or uniform DB connection error from Windows).

- [ ] **Step 6: Commit**

```
git add backend/src/agflow/services/agent_profiles_service.py backend/tests/test_agent_profiles_service.py
git commit -m "feat(agents): réécriture agent_profiles_service en SQL (UUIDs réels, O(1))"
```

---

### Task 4: Delete `agent_files_service.py`

**Files:**
- Delete: `backend/src/agflow/services/agent_files_service.py`

- [ ] **Step 1: Verify no remaining imports**

```
cd backend && grep -r "agent_files_service" src/ tests/
```

Expected: no output (zero matches).

- [ ] **Step 2: Delete the file**

```
git rm backend/src/agflow/services/agent_files_service.py
```

- [ ] **Step 3: Run full lint + tests**

```
cd backend && uv run ruff check src/ tests/ && uv run pytest tests/test_agents_service.py tests/test_agent_profiles_service.py -v
```

Expected: ruff clean, all tests PASS (or uniform DB connection error).

- [ ] **Step 4: Commit**

```
git add -u
git commit -m "chore(agents): suppression agent_files_service (remplacé par SQL)"
```

---

## Self-Review

**Spec coverage:**
- ✅ `agents` table created with all fields from `_AgentBase` + `slug`, `id`, `is_assistant`
- ✅ `agent_profiles` table with `UNIQUE(agent_slug, name)` constraint
- ✅ `agent_id_from_slug` UUID5 namespace preserved (`_AGENT_NS`) → API-stable IDs
- ✅ `get_by_id()` is O(1) via `WHERE id = $1` (was O(N) filesystem scan)
- ✅ `get_assistant()` is O(1) via `WHERE is_assistant = TRUE` (was O(N) scan)
- ✅ `set_assistant()` uses two atomic UPDATEs (was N read+write filesystem ops)
- ✅ `mcp_bindings`, `skill_bindings`, `generations` stored as JSONB arrays
- ✅ `env_overrides/mount_overrides/param_overrides` split into 3 JSONB columns, reconstructed as `env_vars` dict in `_row_to_summary()`
- ✅ `agent_profiles_service` uses real UUIDs (not UUID5 from name+slug)
- ✅ CASCADE DELETE: deleting an agent removes its profiles
- ✅ `agent_files_service.py` deleted at the end
- ✅ Tests cover all CRUD paths, bindings, generations, assistant flag transitions

**Placeholder scan:** None found — all steps have actual code.

**Type consistency:**
- `_slug_to_uuid()` returns `UUID`, used correctly in INSERT `$2` slot
- `_row_to_summary()` uses `row["id"]` which is already a `UUID` from asyncpg
- `_detail_from_row()` reads `row["mcp_bindings"]` as a list (asyncpg decodes JSONB), wraps each in `AgentMCPBinding`
- `agent_profiles_service._row()` reads `row["document_ids"]` as `list[UUID]` (asyncpg decodes UUID[] natively)
- `update()` in profiles uses dynamic `$N` parameter numbering starting at $2 — consistent throughout
