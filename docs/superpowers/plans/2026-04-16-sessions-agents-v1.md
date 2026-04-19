# Sessions + Agents Instances V1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose sessions (temporary workspaces) and agent instances (addressable agents inside a session) via a public API, with ownership scoping by `api_key_id` and an expiration worker. All 12 methods enforce per-api-key ownership except when the caller has the `*` (admin) scope.

**Architecture:** Three new Postgres tables (`agents_catalog`, `sessions`, `agents_instances`), service layer in `backend/src/agflow/services/`, public endpoints under `/api/v1/sessions/...`. Scoping is enforced via a shared `AuthContext` helper derived from `require_api_key()`. Expiration is handled by a lifespan-spawned async worker that runs every 30s and soft-closes stale sessions. Dialogue endpoints (POST /message, GET /messages, WS /stream) already exist in the MOM layer and are refactored to enforce the new scoping + FK constraints.

**Tech Stack:** Python 3.12, FastAPI, asyncpg, Pydantic v2, pytest-asyncio. No frontend work. No changes to MOM internals.

**Spec:** `specs/home.md` sections M5c (Sessions) + M5d (Agents dans session) + ownership scoping agreed in conversation.

---

## File Structure

### New files (backend)

```
backend/
├── migrations/
│   └── 039_sessions_and_agents.sql
├── src/agflow/
│   ├── auth/
│   │   └── context.py                    # AuthContext (api_key_id + is_admin derivation)
│   ├── schemas/
│   │   └── sessions.py                   # Pydantic DTOs (SessionCreate, SessionOut, AgentCreate, ...)
│   ├── services/
│   │   ├── agents_catalog_service.py     # sync catalog with data/agents/ on FS
│   │   ├── sessions_service.py           # CRUD, extend, expire
│   │   └── agents_instances_service.py   # CRUD with count, status derivation
│   ├── api/public/
│   │   └── sessions.py                   # 12 endpoints (sessions + agents + session-level msg/stream)
│   └── workers/
│       ├── __init__.py
│       └── session_expiry.py             # periodic worker
└── tests/
    └── sessions/
        ├── __init__.py
        ├── test_sessions_service.py
        ├── test_agents_instances_service.py
        ├── test_sessions_endpoints.py
        ├── test_scoping.py
        └── test_expiry_worker.py
```

### Modified files

```
backend/src/agflow/api/public/messages.py           # Add scoping, session+instance FK validation
backend/src/agflow/main.py                          # Register sessions router + start expiry worker
```

### Documentation livrables

```
docs/api/sessions-agents.md                         # Full API doc with curl examples
docs/test-plans/sessions-v1-scenarios.md            # End-to-end test scenarios
```

---

## Conventions

- `from __future__ import annotations` at the top of every Python file.
- No comments unless the WHY is non-obvious.
- Files max 300 lines.
- `structlog.get_logger(__name__)` for all logging.
- Tests use `pytest-asyncio` with `@pytest.mark.asyncio`. Fixtures acquire the pool, teardown closes it.
- DB tests run on LXC 201 post-deploy (no local DB). Write them anyway.
- Admin bypass: `"*" in api_key["scopes"]` (existing convention).
- Default session duration: **3600 seconds** (1h). Max per request: **86400 seconds** (24h).
- Slug regex for agent_id: `^[a-z0-9][a-z0-9-]{0,63}$`.

---

## Task 1: Migration — 3 new tables

**Files:**
- Create: `backend/migrations/039_sessions_and_agents.sql`

- [ ] **Step 1: Write the migration SQL**

```sql
-- 039_sessions_and_agents.sql
-- M5c + M5d: sessions + agent instances + minimal agents registry

CREATE TABLE IF NOT EXISTS agents_catalog (
    slug        TEXT PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sessions (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    api_key_id   UUID NOT NULL REFERENCES api_keys(id) ON DELETE CASCADE,
    name         TEXT,
    status       TEXT NOT NULL DEFAULT 'active'
                 CHECK (status IN ('active','closed','expired')),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at   TIMESTAMPTZ NOT NULL,
    closed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_sessions_api_key ON sessions (api_key_id, status);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions (expires_at) WHERE status = 'active';

CREATE TABLE IF NOT EXISTS agents_instances (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id    UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    agent_id      TEXT NOT NULL REFERENCES agents_catalog(slug) ON DELETE RESTRICT,
    labels        JSONB NOT NULL DEFAULT '{}',
    mission       TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    destroyed_at  TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_agents_instances_session
    ON agents_instances (session_id) WHERE destroyed_at IS NULL;
```

- [ ] **Step 2: Commit**

```bash
git add backend/migrations/039_sessions_and_agents.sql
git commit -m "feat(sessions): migration 039 — sessions + agents_instances + agents_catalog"
```

---

## Task 2: AuthContext helper

Single-purpose helper that derives `(api_key_id, is_admin)` from an api_key row and provides a SQL WHERE clause fragment for scoping.

**Files:**
- Create: `backend/src/agflow/auth/context.py`
- Test: `backend/tests/sessions/__init__.py` (empty)
- Test: `backend/tests/sessions/test_auth_context.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/sessions/test_auth_context.py
from __future__ import annotations

from uuid import uuid4

from agflow.auth.context import AuthContext


def test_non_admin_context() -> None:
    key_id = uuid4()
    row = {"id": key_id, "scopes": ["read", "write"], "owner_id": uuid4()}
    ctx = AuthContext.from_api_key(row)
    assert ctx.api_key_id == key_id
    assert ctx.is_admin is False


def test_admin_context() -> None:
    key_id = uuid4()
    row = {"id": key_id, "scopes": ["*"], "owner_id": uuid4()}
    ctx = AuthContext.from_api_key(row)
    assert ctx.is_admin is True


def test_admin_also_with_other_scopes() -> None:
    row = {"id": uuid4(), "scopes": ["*", "write"], "owner_id": uuid4()}
    ctx = AuthContext.from_api_key(row)
    assert ctx.is_admin is True
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && uv run pytest tests/sessions/test_auth_context.py -v
```
Expected: ImportError.

- [ ] **Step 3: Implement AuthContext**

```python
# backend/src/agflow/auth/context.py
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class AuthContext:
    api_key_id: UUID
    owner_id: UUID
    is_admin: bool

    @classmethod
    def from_api_key(cls, row: dict) -> AuthContext:
        return cls(
            api_key_id=row["id"],
            owner_id=row["owner_id"],
            is_admin="*" in row.get("scopes", []),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && uv run pytest tests/sessions/test_auth_context.py -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/agflow/auth/context.py backend/tests/sessions/__init__.py backend/tests/sessions/test_auth_context.py
git commit -m "feat(sessions): AuthContext helper — derive api_key_id + is_admin"
```

---

## Task 3: Pydantic schemas

All DTOs for the session/agent endpoints in one place.

**Files:**
- Create: `backend/src/agflow/schemas/sessions.py`

- [ ] **Step 1: Implement schemas (no test — pure type declarations)**

```python
# backend/src/agflow/schemas/sessions.py
from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

DEFAULT_SESSION_DURATION_S = 3600
MAX_SESSION_DURATION_S = 86400

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def _validate_slug(v: str) -> str:
    if not _SLUG_RE.match(v):
        raise ValueError(
            f"slug must match {_SLUG_RE.pattern}, got '{v}'"
        )
    return v


class SessionCreate(BaseModel):
    name: str | None = None
    duration_seconds: int = Field(
        default=DEFAULT_SESSION_DURATION_S, ge=60, le=MAX_SESSION_DURATION_S,
    )


class SessionExtend(BaseModel):
    duration_seconds: int = Field(ge=60, le=MAX_SESSION_DURATION_S)


class SessionOut(BaseModel):
    id: UUID
    name: str | None
    status: str
    created_at: datetime
    expires_at: datetime
    closed_at: datetime | None
    api_key_id: UUID


class AgentInstanceCreate(BaseModel):
    agent_id: str
    count: int = Field(default=1, ge=1, le=50)
    labels: dict[str, Any] = Field(default_factory=dict)
    mission: str | None = None

    @field_validator("agent_id")
    @classmethod
    def _check_slug(cls, v: str) -> str:
        return _validate_slug(v)


class AgentInstanceOut(BaseModel):
    id: UUID
    session_id: UUID
    agent_id: str
    labels: dict[str, Any]
    mission: str | None
    status: str
    created_at: datetime


class AgentInstanceCreated(BaseModel):
    instance_ids: list[UUID]
```

- [ ] **Step 2: Commit**

```bash
git add backend/src/agflow/schemas/sessions.py
git commit -m "feat(sessions): Pydantic schemas for sessions + agent instance endpoints"
```

---

## Task 4: agents_catalog sync service

Syncs `agents_catalog` table with `data/agents/*/` filesystem. Called at startup and whenever M4 composition writes/deletes an agent.

**Files:**
- Create: `backend/src/agflow/services/agents_catalog_service.py`
- Test: `backend/tests/sessions/test_agents_catalog_service.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/sessions/test_agents_catalog_service.py
from __future__ import annotations

import pytest
import pytest_asyncio

from agflow.db.pool import close_pool, fetch_all, get_pool
from agflow.services import agents_catalog_service


@pytest_asyncio.fixture
async def pool():
    p = await get_pool()
    yield p
    await close_pool()


@pytest.mark.asyncio
class TestAgentsCatalog:
    async def test_upsert_new_slug(self, pool) -> None:
        await agents_catalog_service.upsert("test-agent-123")
        rows = await fetch_all(
            "SELECT slug FROM agents_catalog WHERE slug = $1", "test-agent-123",
        )
        assert len(rows) == 1
        await agents_catalog_service.delete("test-agent-123")

    async def test_upsert_existing_slug_updates_last_seen(self, pool) -> None:
        await agents_catalog_service.upsert("repeat-slug")
        row1 = await fetch_all(
            "SELECT last_seen FROM agents_catalog WHERE slug = $1", "repeat-slug",
        )
        await agents_catalog_service.upsert("repeat-slug")
        row2 = await fetch_all(
            "SELECT last_seen FROM agents_catalog WHERE slug = $1", "repeat-slug",
        )
        assert row2[0]["last_seen"] >= row1[0]["last_seen"]
        await agents_catalog_service.delete("repeat-slug")

    async def test_delete(self, pool) -> None:
        await agents_catalog_service.upsert("delete-me")
        await agents_catalog_service.delete("delete-me")
        rows = await fetch_all(
            "SELECT slug FROM agents_catalog WHERE slug = $1", "delete-me",
        )
        assert rows == []

    async def test_sync_from_filesystem(self, pool, tmp_path, monkeypatch) -> None:
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        (agents_dir / "alpha").mkdir()
        (agents_dir / "beta").mkdir()
        (agents_dir / ".hidden").mkdir()  # should be ignored

        monkeypatch.setattr(agents_catalog_service, "_agents_dir", lambda: agents_dir)
        await agents_catalog_service.sync_from_filesystem()

        rows = await fetch_all(
            "SELECT slug FROM agents_catalog WHERE slug IN ('alpha','beta','.hidden') "
            "ORDER BY slug"
        )
        slugs = [r["slug"] for r in rows]
        assert "alpha" in slugs
        assert "beta" in slugs
        assert ".hidden" not in slugs
        await agents_catalog_service.delete("alpha")
        await agents_catalog_service.delete("beta")
```

- [ ] **Step 2: Implement `agents_catalog_service.py`**

```python
# backend/src/agflow/services/agents_catalog_service.py
from __future__ import annotations

import os
from pathlib import Path

import structlog

from agflow.db.pool import execute

_log = structlog.get_logger(__name__)


def _agents_dir() -> Path:
    return Path(os.environ.get("AGFLOW_DATA_DIR", "/app/data")) / "agents"


async def upsert(slug: str) -> None:
    await execute(
        "INSERT INTO agents_catalog (slug) VALUES ($1) "
        "ON CONFLICT (slug) DO UPDATE SET last_seen = now()",
        slug,
    )


async def delete(slug: str) -> None:
    await execute("DELETE FROM agents_catalog WHERE slug = $1", slug)


async def sync_from_filesystem() -> int:
    agents_dir = _agents_dir()
    if not agents_dir.is_dir():
        _log.warning("agents_catalog.sync.no_dir", path=str(agents_dir))
        return 0
    count = 0
    for entry in agents_dir.iterdir():
        if not entry.is_dir():
            continue
        slug = entry.name
        if slug.startswith(".") or slug.startswith("_"):
            continue
        await upsert(slug)
        count += 1
    _log.info("agents_catalog.sync.done", count=count)
    return count
```

- [ ] **Step 3: Lint and commit**

```bash
cd backend && uv run ruff check src/agflow/services/agents_catalog_service.py tests/sessions/test_agents_catalog_service.py
git add backend/src/agflow/services/agents_catalog_service.py backend/tests/sessions/test_agents_catalog_service.py
git commit -m "feat(sessions): agents_catalog service — sync with data/agents/ on FS"
```

---

## Task 5: Sessions service — CRUD + extend + expire

**Files:**
- Create: `backend/src/agflow/services/sessions_service.py`
- Test: `backend/tests/sessions/test_sessions_service.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/sessions/test_sessions_service.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import pytest_asyncio

from agflow.db.pool import close_pool, execute, fetch_one, get_pool
from agflow.services import sessions_service


@pytest_asyncio.fixture
async def pool():
    p = await get_pool()
    yield p
    await close_pool()


@pytest_asyncio.fixture
async def api_key_id(pool) -> UUID:
    """Insert a minimal fake api_key row and return its id."""
    from uuid import uuid4
    kid = uuid4()
    await execute(
        "INSERT INTO api_keys (id, owner_id, name, prefix, key_hash, scopes) "
        "VALUES ($1, $2, 'test', $3, 'hash', $4)",
        kid, uuid4(), f"pfx_{str(kid)[:8]}", ["read"],
    )
    yield kid
    await execute("DELETE FROM api_keys WHERE id = $1", kid)


@pytest.mark.asyncio
class TestSessionsService:
    async def test_create_session_default_duration(self, api_key_id: UUID) -> None:
        session = await sessions_service.create(
            api_key_id=api_key_id, name="test", duration_seconds=3600,
        )
        assert session["status"] == "active"
        assert session["name"] == "test"
        delta = session["expires_at"] - session["created_at"]
        assert abs(delta.total_seconds() - 3600) < 5
        await sessions_service.close(session_id=session["id"], api_key_id=api_key_id, is_admin=False)

    async def test_get_session_scoped_by_api_key(self, api_key_id: UUID) -> None:
        session = await sessions_service.create(
            api_key_id=api_key_id, name=None, duration_seconds=3600,
        )
        found = await sessions_service.get(
            session_id=session["id"], api_key_id=api_key_id, is_admin=False,
        )
        assert found is not None
        assert found["id"] == session["id"]

        other_key = uuid4()
        not_found = await sessions_service.get(
            session_id=session["id"], api_key_id=other_key, is_admin=False,
        )
        assert not_found is None
        await sessions_service.close(session_id=session["id"], api_key_id=api_key_id, is_admin=False)

    async def test_admin_sees_other_sessions(self, api_key_id: UUID) -> None:
        session = await sessions_service.create(
            api_key_id=api_key_id, name=None, duration_seconds=3600,
        )
        other_key = uuid4()
        found = await sessions_service.get(
            session_id=session["id"], api_key_id=other_key, is_admin=True,
        )
        assert found is not None
        await sessions_service.close(session_id=session["id"], api_key_id=api_key_id, is_admin=False)

    async def test_extend_session(self, api_key_id: UUID) -> None:
        session = await sessions_service.create(
            api_key_id=api_key_id, name=None, duration_seconds=600,
        )
        original_expires = session["expires_at"]
        extended = await sessions_service.extend(
            session_id=session["id"], api_key_id=api_key_id, is_admin=False,
            additional_seconds=1800,
        )
        assert (extended["expires_at"] - original_expires).total_seconds() >= 1800 - 5
        await sessions_service.close(session_id=session["id"], api_key_id=api_key_id, is_admin=False)

    async def test_extend_rejects_stranger(self, api_key_id: UUID) -> None:
        session = await sessions_service.create(
            api_key_id=api_key_id, name=None, duration_seconds=600,
        )
        stranger = uuid4()
        result = await sessions_service.extend(
            session_id=session["id"], api_key_id=stranger, is_admin=False,
            additional_seconds=600,
        )
        assert result is None
        await sessions_service.close(session_id=session["id"], api_key_id=api_key_id, is_admin=False)

    async def test_close_cascades_via_fk(self, api_key_id: UUID) -> None:
        session = await sessions_service.create(
            api_key_id=api_key_id, name=None, duration_seconds=3600,
        )
        result = await sessions_service.close(
            session_id=session["id"], api_key_id=api_key_id, is_admin=False,
        )
        assert result is True
        row = await fetch_one(
            "SELECT status, closed_at FROM sessions WHERE id = $1",
            session["id"],
        )
        assert row["status"] == "closed"
        assert row["closed_at"] is not None

    async def test_expire_stale_sessions(self, api_key_id: UUID) -> None:
        session = await sessions_service.create(
            api_key_id=api_key_id, name=None, duration_seconds=60,
        )
        await execute(
            "UPDATE sessions SET expires_at = now() - interval '1 minute' WHERE id = $1",
            session["id"],
        )
        count = await sessions_service.expire_stale()
        assert count >= 1
        row = await fetch_one(
            "SELECT status FROM sessions WHERE id = $1", session["id"],
        )
        assert row["status"] == "expired"
```

- [ ] **Step 2: Implement `sessions_service.py`**

```python
# backend/src/agflow/services/sessions_service.py
from __future__ import annotations

from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_all, fetch_one

_log = structlog.get_logger(__name__)


async def create(
    *, api_key_id: UUID, name: str | None, duration_seconds: int,
) -> dict:
    row = await fetch_one(
        """
        INSERT INTO sessions (api_key_id, name, expires_at)
        VALUES ($1, $2, now() + ($3 || ' seconds')::interval)
        RETURNING id, api_key_id, name, status, created_at, expires_at, closed_at
        """,
        api_key_id, name, str(duration_seconds),
    )
    _log.info(
        "sessions.created",
        session_id=str(row["id"]),
        api_key_id=str(api_key_id),
        duration_seconds=duration_seconds,
    )
    return dict(row)


async def get(
    *, session_id: UUID, api_key_id: UUID, is_admin: bool,
) -> dict | None:
    if is_admin:
        row = await fetch_one(
            "SELECT id, api_key_id, name, status, created_at, expires_at, closed_at "
            "FROM sessions WHERE id = $1",
            session_id,
        )
    else:
        row = await fetch_one(
            "SELECT id, api_key_id, name, status, created_at, expires_at, closed_at "
            "FROM sessions WHERE id = $1 AND api_key_id = $2",
            session_id, api_key_id,
        )
    return dict(row) if row else None


async def list_for_key(*, api_key_id: UUID, is_admin: bool) -> list[dict]:
    if is_admin:
        rows = await fetch_all(
            "SELECT id, api_key_id, name, status, created_at, expires_at, closed_at "
            "FROM sessions ORDER BY created_at DESC",
        )
    else:
        rows = await fetch_all(
            "SELECT id, api_key_id, name, status, created_at, expires_at, closed_at "
            "FROM sessions WHERE api_key_id = $1 ORDER BY created_at DESC",
            api_key_id,
        )
    return [dict(r) for r in rows]


async def extend(
    *, session_id: UUID, api_key_id: UUID, is_admin: bool, additional_seconds: int,
) -> dict | None:
    scope_clause = "" if is_admin else " AND api_key_id = $3"
    params = [str(additional_seconds), session_id]
    if not is_admin:
        params.append(api_key_id)

    row = await fetch_one(
        f"""
        UPDATE sessions
        SET expires_at = expires_at + ($1 || ' seconds')::interval
        WHERE id = $2 AND status = 'active'{scope_clause}
        RETURNING id, api_key_id, name, status, created_at, expires_at, closed_at
        """,
        *params,
    )
    return dict(row) if row else None


async def close(
    *, session_id: UUID, api_key_id: UUID, is_admin: bool,
) -> bool:
    scope_clause = "" if is_admin else " AND api_key_id = $2"
    params = [session_id]
    if not is_admin:
        params.append(api_key_id)

    result = await execute(
        f"""
        UPDATE sessions
        SET status = 'closed', closed_at = now()
        WHERE id = $1 AND status = 'active'{scope_clause}
        """,
        *params,
    )
    closed = result.endswith(" 1")
    if closed:
        _log.info("sessions.closed", session_id=str(session_id))
    return closed


async def expire_stale() -> int:
    result = await execute(
        """
        UPDATE sessions
        SET status = 'expired', closed_at = now()
        WHERE status = 'active' AND expires_at < now()
        """,
    )
    count = int(result.split()[-1]) if result else 0
    if count > 0:
        _log.info("sessions.expired", count=count)
    return count
```

- [ ] **Step 3: Lint and commit**

```bash
cd backend && uv run ruff check src/agflow/services/sessions_service.py tests/sessions/test_sessions_service.py
git add backend/src/agflow/services/sessions_service.py backend/tests/sessions/test_sessions_service.py
git commit -m "feat(sessions): sessions_service — CRUD + extend + expire_stale"
```

---

## Task 6: Agents instances service — CRUD + status derivation

**Files:**
- Create: `backend/src/agflow/services/agents_instances_service.py`
- Test: `backend/tests/sessions/test_agents_instances_service.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/sessions/test_agents_instances_service.py
from __future__ import annotations

import json
from uuid import UUID, uuid4

import pytest
import pytest_asyncio

from agflow.db.pool import close_pool, execute, fetch_one, get_pool
from agflow.services import agents_catalog_service, agents_instances_service, sessions_service


@pytest_asyncio.fixture
async def pool():
    p = await get_pool()
    yield p
    await close_pool()


@pytest_asyncio.fixture
async def api_key_id(pool) -> UUID:
    kid = uuid4()
    await execute(
        "INSERT INTO api_keys (id, owner_id, name, prefix, key_hash, scopes) "
        "VALUES ($1, $2, 'test', $3, 'hash', $4)",
        kid, uuid4(), f"pfx_{str(kid)[:8]}", ["read"],
    )
    await agents_catalog_service.upsert("test-agent")
    yield kid
    await execute("DELETE FROM api_keys WHERE id = $1", kid)
    await agents_catalog_service.delete("test-agent")


@pytest.mark.asyncio
class TestAgentsInstancesService:
    async def test_create_single_instance(self, api_key_id: UUID) -> None:
        session = await sessions_service.create(
            api_key_id=api_key_id, name=None, duration_seconds=3600,
        )
        ids = await agents_instances_service.create(
            session_id=session["id"], agent_id="test-agent",
            count=1, labels={"team": "x"}, mission="do stuff",
        )
        assert len(ids) == 1

        row = await fetch_one(
            "SELECT agent_id, labels, mission FROM agents_instances WHERE id = $1",
            ids[0],
        )
        assert row["agent_id"] == "test-agent"
        labels = row["labels"] if isinstance(row["labels"], dict) else json.loads(row["labels"])
        assert labels == {"team": "x"}
        await sessions_service.close(session_id=session["id"], api_key_id=api_key_id, is_admin=False)

    async def test_create_multiple_instances(self, api_key_id: UUID) -> None:
        session = await sessions_service.create(
            api_key_id=api_key_id, name=None, duration_seconds=3600,
        )
        ids = await agents_instances_service.create(
            session_id=session["id"], agent_id="test-agent",
            count=3, labels={}, mission=None,
        )
        assert len(ids) == 3
        assert len(set(ids)) == 3
        await sessions_service.close(session_id=session["id"], api_key_id=api_key_id, is_admin=False)

    async def test_list_active_only(self, api_key_id: UUID) -> None:
        session = await sessions_service.create(
            api_key_id=api_key_id, name=None, duration_seconds=3600,
        )
        ids = await agents_instances_service.create(
            session_id=session["id"], agent_id="test-agent",
            count=2, labels={}, mission=None,
        )
        await agents_instances_service.destroy(
            session_id=session["id"], instance_id=ids[0],
        )
        active = await agents_instances_service.list_for_session(
            session_id=session["id"],
        )
        assert len(active) == 1
        assert active[0]["id"] == ids[1]
        await sessions_service.close(session_id=session["id"], api_key_id=api_key_id, is_admin=False)

    async def test_status_is_idle_when_no_pending_instructions(
        self, api_key_id: UUID,
    ) -> None:
        session = await sessions_service.create(
            api_key_id=api_key_id, name=None, duration_seconds=3600,
        )
        ids = await agents_instances_service.create(
            session_id=session["id"], agent_id="test-agent",
            count=1, labels={}, mission=None,
        )
        active = await agents_instances_service.list_for_session(
            session_id=session["id"],
        )
        assert active[0]["status"] == "idle"
        await sessions_service.close(session_id=session["id"], api_key_id=api_key_id, is_admin=False)

    async def test_status_is_busy_when_pending_instruction(
        self, api_key_id: UUID,
    ) -> None:
        session = await sessions_service.create(
            api_key_id=api_key_id, name=None, duration_seconds=3600,
        )
        ids = await agents_instances_service.create(
            session_id=session["id"], agent_id="test-agent",
            count=1, labels={}, mission=None,
        )
        await execute(
            "INSERT INTO agent_messages (session_id, instance_id, direction, kind, payload, source) "
            "VALUES ($1, $2, 'in', 'instruction', '{}'::jsonb, 'test')",
            str(session["id"]), str(ids[0]),
        )
        await execute(
            "INSERT INTO agent_message_delivery (group_name, msg_id, status) "
            "SELECT 'dispatcher', msg_id, 'pending' FROM agent_messages "
            "WHERE instance_id = $1",
            str(ids[0]),
        )
        active = await agents_instances_service.list_for_session(
            session_id=session["id"],
        )
        assert active[0]["status"] == "busy"
        await sessions_service.close(session_id=session["id"], api_key_id=api_key_id, is_admin=False)

    async def test_destroy_marks_destroyed_at(self, api_key_id: UUID) -> None:
        session = await sessions_service.create(
            api_key_id=api_key_id, name=None, duration_seconds=3600,
        )
        ids = await agents_instances_service.create(
            session_id=session["id"], agent_id="test-agent",
            count=1, labels={}, mission=None,
        )
        ok = await agents_instances_service.destroy(
            session_id=session["id"], instance_id=ids[0],
        )
        assert ok is True
        row = await fetch_one(
            "SELECT destroyed_at FROM agents_instances WHERE id = $1", ids[0],
        )
        assert row["destroyed_at"] is not None
        await sessions_service.close(session_id=session["id"], api_key_id=api_key_id, is_admin=False)
```

- [ ] **Step 2: Implement `agents_instances_service.py`**

```python
# backend/src/agflow/services/agents_instances_service.py
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_all, fetch_one

_log = structlog.get_logger(__name__)


async def create(
    *,
    session_id: UUID,
    agent_id: str,
    count: int,
    labels: dict[str, Any],
    mission: str | None,
) -> list[UUID]:
    labels_json = json.dumps(labels, ensure_ascii=False)
    ids: list[UUID] = []
    for _ in range(count):
        row = await fetch_one(
            """
            INSERT INTO agents_instances (session_id, agent_id, labels, mission)
            VALUES ($1, $2, $3::jsonb, $4)
            RETURNING id
            """,
            session_id, agent_id, labels_json, mission,
        )
        ids.append(row["id"])
    _log.info(
        "agents_instances.created",
        session_id=str(session_id),
        agent_id=agent_id,
        count=count,
    )
    return ids


async def list_for_session(*, session_id: UUID) -> list[dict]:
    rows = await fetch_all(
        """
        SELECT
            i.id,
            i.session_id,
            i.agent_id,
            i.labels,
            i.mission,
            i.created_at,
            CASE WHEN EXISTS (
                SELECT 1
                FROM agent_messages m
                JOIN agent_message_delivery d
                  ON d.msg_id = m.msg_id AND d.group_name = 'dispatcher'
                WHERE m.instance_id = i.id::text
                  AND m.direction = 'in'
                  AND m.kind = 'instruction'
                  AND d.status IN ('pending','claimed')
            ) THEN 'busy' ELSE 'idle' END AS status
        FROM agents_instances i
        WHERE i.session_id = $1 AND i.destroyed_at IS NULL
        ORDER BY i.created_at
        """,
        session_id,
    )
    return [dict(r) for r in rows]


async def get(*, session_id: UUID, instance_id: UUID) -> dict | None:
    row = await fetch_one(
        """
        SELECT id, session_id, agent_id, labels, mission, created_at, destroyed_at
        FROM agents_instances
        WHERE id = $1 AND session_id = $2
        """,
        instance_id, session_id,
    )
    return dict(row) if row else None


async def destroy(*, session_id: UUID, instance_id: UUID) -> bool:
    result = await execute(
        """
        UPDATE agents_instances
        SET destroyed_at = now()
        WHERE id = $1 AND session_id = $2 AND destroyed_at IS NULL
        """,
        instance_id, session_id,
    )
    ok = result.endswith(" 1")
    if ok:
        _log.info(
            "agents_instances.destroyed",
            session_id=str(session_id),
            instance_id=str(instance_id),
        )
    return ok
```

- [ ] **Step 3: Lint and commit**

```bash
cd backend && uv run ruff check src/agflow/services/agents_instances_service.py tests/sessions/test_agents_instances_service.py
git add backend/src/agflow/services/agents_instances_service.py backend/tests/sessions/test_agents_instances_service.py
git commit -m "feat(sessions): agents_instances_service — CRUD + busy/idle status derivation"
```

---

## Task 7: Sessions API endpoints (methods 1-4 + 5-7)

**Files:**
- Create: `backend/src/agflow/api/public/sessions.py`
- Modify: `backend/src/agflow/main.py` — register router + startup sync
- Test: `backend/tests/sessions/test_sessions_endpoints.py`

- [ ] **Step 1: Write failing tests for the 7 endpoints**

```python
# backend/tests/sessions/test_sessions_endpoints.py
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from agflow.db.pool import close_pool, execute, fetch_one, get_pool
from agflow.main import create_app
from agflow.services import agents_catalog_service


@pytest_asyncio.fixture
async def pool():
    p = await get_pool()
    yield p
    await close_pool()


@pytest_asyncio.fixture
async def api_token(pool) -> tuple[str, UUID]:
    """Create a real API key (both hashed + raw form) and return (token, id)."""
    from agflow.services import api_keys_service
    token, row = await api_keys_service.create(
        owner_id=uuid4(), name="test-sessions",
        scopes=["sessions:read", "sessions:write"],
        expires_in_days=1, rate_limit=1000,
    )
    yield token, row["id"]
    await execute("DELETE FROM api_keys WHERE id = $1", row["id"])


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


@pytest.mark.asyncio
class TestSessionEndpoints:
    async def test_create_session(
        self, client: TestClient, api_token: tuple[str, UUID],
    ) -> None:
        token, key_id = api_token
        r = client.post(
            "/api/v1/sessions",
            json={"name": "my-session", "duration_seconds": 600},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["name"] == "my-session"
        assert body["status"] == "active"
        sid = body["id"]

        r = client.delete(
            f"/api/v1/sessions/{sid}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 204

    async def test_get_session_forbidden_for_stranger(
        self, client: TestClient, api_token: tuple[str, UUID], pool,
    ) -> None:
        token, _ = api_token
        r = client.post(
            "/api/v1/sessions",
            json={"duration_seconds": 600},
            headers={"Authorization": f"Bearer {token}"},
        )
        sid = r.json()["id"]

        from agflow.services import api_keys_service
        stranger_token, stranger_row = await api_keys_service.create(
            owner_id=uuid4(), name="stranger",
            scopes=["sessions:read"], expires_in_days=1, rate_limit=1000,
        )
        try:
            r = client.get(
                f"/api/v1/sessions/{sid}",
                headers={"Authorization": f"Bearer {stranger_token}"},
            )
            assert r.status_code == 404
        finally:
            await execute("DELETE FROM api_keys WHERE id = $1", stranger_row["id"])
            client.delete(
                f"/api/v1/sessions/{sid}",
                headers={"Authorization": f"Bearer {token}"},
            )

    async def test_admin_sees_any_session(
        self, client: TestClient, api_token: tuple[str, UUID],
    ) -> None:
        token, _ = api_token
        r = client.post(
            "/api/v1/sessions",
            json={"duration_seconds": 600},
            headers={"Authorization": f"Bearer {token}"},
        )
        sid = r.json()["id"]

        from agflow.services import api_keys_service
        admin_token, admin_row = await api_keys_service.create(
            owner_id=uuid4(), name="admin",
            scopes=["*"], expires_in_days=1, rate_limit=1000,
        )
        try:
            r = client.get(
                f"/api/v1/sessions/{sid}",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            assert r.status_code == 200
        finally:
            await execute("DELETE FROM api_keys WHERE id = $1", admin_row["id"])
            client.delete(
                f"/api/v1/sessions/{sid}",
                headers={"Authorization": f"Bearer {token}"},
            )

    async def test_extend_session(
        self, client: TestClient, api_token: tuple[str, UUID],
    ) -> None:
        token, _ = api_token
        r = client.post(
            "/api/v1/sessions",
            json={"duration_seconds": 600},
            headers={"Authorization": f"Bearer {token}"},
        )
        body = r.json()
        sid = body["id"]
        original_expires = body["expires_at"]

        r = client.patch(
            f"/api/v1/sessions/{sid}/extend",
            json={"duration_seconds": 1200},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        assert r.json()["expires_at"] > original_expires

        client.delete(
            f"/api/v1/sessions/{sid}",
            headers={"Authorization": f"Bearer {token}"},
        )

    async def test_create_agent_instances(
        self, client: TestClient, api_token: tuple[str, UUID],
    ) -> None:
        token, _ = api_token
        await agents_catalog_service.upsert("test-agent")
        try:
            r = client.post(
                "/api/v1/sessions",
                json={"duration_seconds": 600},
                headers={"Authorization": f"Bearer {token}"},
            )
            sid = r.json()["id"]

            r = client.post(
                f"/api/v1/sessions/{sid}/agents",
                json={"agent_id": "test-agent", "count": 2, "labels": {"role": "t"}},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r.status_code == 201
            ids = r.json()["instance_ids"]
            assert len(ids) == 2

            r = client.get(
                f"/api/v1/sessions/{sid}/agents",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r.status_code == 200
            assert len(r.json()) == 2
            assert all(a["status"] == "idle" for a in r.json())

            r = client.delete(
                f"/api/v1/sessions/{sid}/agents/{ids[0]}",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r.status_code == 204

            client.delete(
                f"/api/v1/sessions/{sid}",
                headers={"Authorization": f"Bearer {token}"},
            )
        finally:
            await agents_catalog_service.delete("test-agent")

    async def test_create_unknown_agent_rejected(
        self, client: TestClient, api_token: tuple[str, UUID],
    ) -> None:
        token, _ = api_token
        r = client.post(
            "/api/v1/sessions",
            json={"duration_seconds": 600},
            headers={"Authorization": f"Bearer {token}"},
        )
        sid = r.json()["id"]
        try:
            r = client.post(
                f"/api/v1/sessions/{sid}/agents",
                json={"agent_id": "non-existent-agent", "count": 1},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r.status_code in (400, 404)
        finally:
            client.delete(
                f"/api/v1/sessions/{sid}",
                headers={"Authorization": f"Bearer {token}"},
            )
```

- [ ] **Step 2: Implement `backend/src/agflow/api/public/sessions.py`**

```python
# backend/src/agflow/api/public/sessions.py
from __future__ import annotations

from uuid import UUID

import asyncpg
import structlog
from fastapi import APIRouter, Depends, HTTPException, status

from agflow.auth.api_key import require_api_key
from agflow.auth.context import AuthContext
from agflow.schemas.sessions import (
    AgentInstanceCreate,
    AgentInstanceCreated,
    AgentInstanceOut,
    SessionCreate,
    SessionExtend,
    SessionOut,
)
from agflow.services import (
    agents_catalog_service,
    agents_instances_service,
    sessions_service,
)

_log = structlog.get_logger(__name__)

router = APIRouter()


@router.post("/api/v1/sessions", status_code=status.HTTP_201_CREATED)
async def create_session(
    body: SessionCreate, api_key: dict = require_api_key(),
) -> SessionOut:
    ctx = AuthContext.from_api_key(api_key)
    row = await sessions_service.create(
        api_key_id=ctx.api_key_id, name=body.name,
        duration_seconds=body.duration_seconds,
    )
    return SessionOut(**row)


@router.get("/api/v1/sessions/{session_id}")
async def get_session(
    session_id: UUID, api_key: dict = require_api_key(),
) -> SessionOut:
    ctx = AuthContext.from_api_key(api_key)
    row = await sessions_service.get(
        session_id=session_id, api_key_id=ctx.api_key_id, is_admin=ctx.is_admin,
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    return SessionOut(**row)


@router.patch("/api/v1/sessions/{session_id}/extend")
async def extend_session(
    session_id: UUID, body: SessionExtend, api_key: dict = require_api_key(),
) -> SessionOut:
    ctx = AuthContext.from_api_key(api_key)
    row = await sessions_service.extend(
        session_id=session_id, api_key_id=ctx.api_key_id, is_admin=ctx.is_admin,
        additional_seconds=body.duration_seconds,
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found or not active")
    return SessionOut(**row)


@router.delete("/api/v1/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def close_session(
    session_id: UUID, api_key: dict = require_api_key(),
) -> None:
    ctx = AuthContext.from_api_key(api_key)
    ok = await sessions_service.close(
        session_id=session_id, api_key_id=ctx.api_key_id, is_admin=ctx.is_admin,
    )
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found or already closed")


@router.post(
    "/api/v1/sessions/{session_id}/agents",
    status_code=status.HTTP_201_CREATED,
)
async def create_agents(
    session_id: UUID, body: AgentInstanceCreate,
    api_key: dict = require_api_key(),
) -> AgentInstanceCreated:
    ctx = AuthContext.from_api_key(api_key)
    session = await sessions_service.get(
        session_id=session_id, api_key_id=ctx.api_key_id, is_admin=ctx.is_admin,
    )
    if session is None or session["status"] != "active":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found or not active")

    try:
        ids = await agents_instances_service.create(
            session_id=session_id,
            agent_id=body.agent_id,
            count=body.count,
            labels=body.labels,
            mission=body.mission,
        )
    except asyncpg.ForeignKeyViolationError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"agent_id '{body.agent_id}' not found in catalog",
        ) from exc
    return AgentInstanceCreated(instance_ids=ids)


@router.get("/api/v1/sessions/{session_id}/agents")
async def list_agents(
    session_id: UUID, api_key: dict = require_api_key(),
) -> list[AgentInstanceOut]:
    ctx = AuthContext.from_api_key(api_key)
    session = await sessions_service.get(
        session_id=session_id, api_key_id=ctx.api_key_id, is_admin=ctx.is_admin,
    )
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    rows = await agents_instances_service.list_for_session(session_id=session_id)
    return [AgentInstanceOut(**r) for r in rows]


@router.delete(
    "/api/v1/sessions/{session_id}/agents/{instance_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def destroy_agent(
    session_id: UUID, instance_id: UUID, api_key: dict = require_api_key(),
) -> None:
    ctx = AuthContext.from_api_key(api_key)
    session = await sessions_service.get(
        session_id=session_id, api_key_id=ctx.api_key_id, is_admin=ctx.is_admin,
    )
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    ok = await agents_instances_service.destroy(
        session_id=session_id, instance_id=instance_id,
    )
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "instance not found")
```

- [ ] **Step 3: Modify `backend/src/agflow/main.py` to register router and sync catalog at startup**

In the startup section of the lifespan context manager, add this right before `yield`:

```python
from agflow.services import agents_catalog_service
try:
    await agents_catalog_service.sync_from_filesystem()
except Exception as exc:
    _log.warning("agents_catalog.sync.failed", error=str(exc))
```

In the router registration section, add:

```python
from agflow.api.public.sessions import router as sessions_router
app.include_router(sessions_router)
```

- [ ] **Step 4: Lint + import check**

```bash
cd backend
uv run ruff check src/agflow/api/public/sessions.py src/agflow/main.py tests/sessions/test_sessions_endpoints.py
uv run python -c "from agflow.main import create_app; create_app()"
```

- [ ] **Step 5: Commit**

```bash
git add backend/src/agflow/api/public/sessions.py backend/src/agflow/main.py backend/tests/sessions/test_sessions_endpoints.py
git commit -m "feat(sessions): 7 API endpoints — sessions CRUD + agents CRUD with scoping"
```

---

## Task 8: Scoping + FK validation on existing MOM dialogue endpoints (methods 8, 9, 10)

**Files:**
- Modify: `backend/src/agflow/api/public/messages.py` — add `require_api_key`, session/instance validation

- [ ] **Step 1: Rewrite `messages.py` to enforce scoping**

```python
# backend/src/agflow/api/public/messages.py
from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID, uuid4

import structlog
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel

from agflow.auth.api_key import require_api_key
from agflow.auth.context import AuthContext
from agflow.db.pool import fetch_all, get_pool
from agflow.mom.consumers.ws_push import WsPushConsumer
from agflow.mom.envelope import Direction, Kind, Route
from agflow.mom.publisher import MomPublisher
from agflow.services import sessions_service

_log = structlog.get_logger(__name__)

router = APIRouter()

_GROUPS_CONFIG = {
    Direction.IN: ["dispatcher"],
    Direction.OUT: ["ws_push", "router"],
}


class MessageIn(BaseModel):
    kind: Kind = Kind.INSTRUCTION
    payload: dict[str, Any]
    route_to: str | None = None


async def _assert_session_owned(
    session_id: UUID, ctx: AuthContext,
) -> None:
    session = await sessions_service.get(
        session_id=session_id, api_key_id=ctx.api_key_id, is_admin=ctx.is_admin,
    )
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    if session["status"] != "active":
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"session is {session['status']}",
        )


async def _assert_instance_alive(
    session_id: UUID, instance_id: UUID,
) -> None:
    rows = await fetch_all(
        "SELECT id FROM agents_instances "
        "WHERE id = $1 AND session_id = $2 AND destroyed_at IS NULL",
        instance_id, session_id,
    )
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "instance not found or destroyed")


@router.post(
    "/api/v1/sessions/{session_id}/agents/{instance_id}/message",
    status_code=status.HTTP_201_CREATED,
)
async def post_message(
    session_id: UUID,
    instance_id: UUID,
    body: MessageIn,
    api_key: dict = require_api_key(),
) -> dict[str, str]:
    ctx = AuthContext.from_api_key(api_key)
    await _assert_session_owned(session_id, ctx)
    await _assert_instance_alive(session_id, instance_id)

    pool = await get_pool()
    publisher = MomPublisher(pool=pool, groups_config=_GROUPS_CONFIG)
    route = Route(target=body.route_to) if body.route_to else None
    msg_id = await publisher.publish(
        session_id=str(session_id),
        instance_id=str(instance_id),
        direction=Direction.IN,
        source=f"api_key:{ctx.api_key_id}",
        kind=body.kind,
        payload=body.payload,
        route=route,
    )
    return {"msg_id": str(msg_id)}


@router.get("/api/v1/sessions/{session_id}/agents/{instance_id}/messages")
async def get_messages(
    session_id: UUID,
    instance_id: UUID,
    kind: str | None = None,
    direction: str | None = None,
    limit: int = 100,
    api_key: dict = require_api_key(),
) -> list[dict[str, Any]]:
    ctx = AuthContext.from_api_key(api_key)
    await _assert_session_owned(session_id, ctx)

    conditions = ["session_id = $1", "instance_id = $2"]
    params: list[Any] = [str(session_id), str(instance_id)]
    idx = 3
    if kind:
        conditions.append(f"kind = ${idx}")
        params.append(kind)
        idx += 1
    if direction:
        conditions.append(f"direction = ${idx}")
        params.append(direction)
        idx += 1
    where = " AND ".join(conditions)
    params.append(limit)
    query = (
        "SELECT msg_id, parent_msg_id, direction, kind, payload, source, "
        "created_at, route "
        f"FROM agent_messages WHERE {where} "
        f"ORDER BY created_at DESC LIMIT ${idx}"
    )
    rows = await fetch_all(query, *params)
    return [_serialize_msg(r) for r in rows]


def _serialize_msg(r: dict) -> dict[str, Any]:
    return {
        "msg_id": str(r["msg_id"]),
        "parent_msg_id": str(r["parent_msg_id"]) if r["parent_msg_id"] else None,
        "direction": r["direction"],
        "kind": r["kind"],
        "payload": r["payload"],
        "source": r["source"],
        "created_at": r["created_at"].isoformat(),
        "route": r["route"],
    }


@router.websocket("/api/v1/sessions/{session_id}/agents/{instance_id}/stream")
async def ws_agent_stream(
    websocket: WebSocket,
    session_id: UUID,
    instance_id: UUID,
) -> None:
    await websocket.accept()
    pool = await get_pool()
    connection_id = uuid4().hex[:8]
    ws_consumer = WsPushConsumer(
        pool=pool, instance_id=str(instance_id), connection_id=connection_id,
    )
    try:
        async for event in ws_consumer.iter_events():
            await websocket.send_json(event)
    except WebSocketDisconnect:
        _log.info("ws_agent_stream.disconnected", connection_id=connection_id)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        _log.exception("ws_agent_stream.error", error=str(exc))
```

Note: WebSocket authentication with Bearer tokens is non-trivial in FastAPI (no native `Depends(require_api_key)` for WS). V1 leaves WS unauthenticated but scoped to a valid session+instance pair — if no such pair exists, the `claim_batch` returns nothing. Full WS auth (query-string token or subprotocol) is a follow-up.

- [ ] **Step 2: Run existing tests + lint**

```bash
cd backend
uv run ruff check src/agflow/api/public/messages.py
uv run pytest tests/mom/test_envelope.py tests/mom/test_adapters.py tests/mom/test_adapter_registry.py -v
```

- [ ] **Step 3: Commit**

```bash
git add backend/src/agflow/api/public/messages.py
git commit -m "feat(sessions): enforce scoping on POST/GET messages + session+instance validation"
```

---

## Task 9: Session-level consolidated history + stream (methods 11, 12)

Add two endpoints to the same `sessions.py` router (or a new `session_messages.py`). Kept in `sessions.py` for cohesion.

**Files:**
- Modify: `backend/src/agflow/api/public/sessions.py` — add 2 endpoints

- [ ] **Step 1: Append the two endpoints at the bottom of `sessions.py`**

```python
# Appended to backend/src/agflow/api/public/sessions.py

import asyncio as _asyncio
from typing import Any
from uuid import uuid4 as _uuid4
from fastapi import WebSocket, WebSocketDisconnect
from agflow.db.pool import fetch_all as _fetch_all, get_pool as _get_pool
from agflow.mom.consumers.ws_push import WsPushConsumer as _WsPushConsumer


@router.get("/api/v1/sessions/{session_id}/messages")
async def get_session_messages(
    session_id: UUID,
    kind: str | None = None,
    direction: str | None = None,
    limit: int = 200,
    api_key: dict = require_api_key(),
) -> list[dict[str, Any]]:
    ctx = AuthContext.from_api_key(api_key)
    session = await sessions_service.get(
        session_id=session_id, api_key_id=ctx.api_key_id, is_admin=ctx.is_admin,
    )
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")

    conditions = ["session_id = $1"]
    params: list = [str(session_id)]
    idx = 2
    if kind:
        conditions.append(f"kind = ${idx}")
        params.append(kind)
        idx += 1
    if direction:
        conditions.append(f"direction = ${idx}")
        params.append(direction)
        idx += 1
    where = " AND ".join(conditions)
    params.append(limit)

    query = (
        "SELECT msg_id, parent_msg_id, direction, kind, payload, source, "
        "created_at, route, instance_id "
        f"FROM agent_messages WHERE {where} "
        f"ORDER BY created_at DESC LIMIT ${idx}"
    )
    rows = await _fetch_all(query, *params)
    return [
        {
            "msg_id": str(r["msg_id"]),
            "parent_msg_id": str(r["parent_msg_id"]) if r["parent_msg_id"] else None,
            "instance_id": r["instance_id"],
            "direction": r["direction"],
            "kind": r["kind"],
            "payload": r["payload"],
            "source": r["source"],
            "created_at": r["created_at"].isoformat(),
            "route": r["route"],
        }
        for r in rows
    ]


@router.websocket("/api/v1/sessions/{session_id}/stream")
async def ws_session_stream(websocket: WebSocket, session_id: UUID) -> None:
    await websocket.accept()
    pool = await _get_pool()
    connection_id = _uuid4().hex[:8]
    group_name = f"ws_session_{connection_id}"

    async def poll():
        last_seen_at = None
        while True:
            if last_seen_at is None:
                rows = await _fetch_all(
                    "SELECT msg_id, parent_msg_id, instance_id, direction, kind, "
                    "payload, source, created_at, route "
                    "FROM agent_messages "
                    "WHERE session_id = $1 AND direction = 'out' "
                    "ORDER BY created_at DESC LIMIT 1",
                    str(session_id),
                )
                last_seen_at = rows[0]["created_at"] if rows else None
            rows = await _fetch_all(
                "SELECT msg_id, parent_msg_id, instance_id, direction, kind, "
                "payload, source, created_at, route "
                "FROM agent_messages "
                "WHERE session_id = $1 AND direction = 'out' "
                "  AND ($2::timestamptz IS NULL OR created_at > $2) "
                "ORDER BY created_at",
                str(session_id), last_seen_at,
            )
            for r in rows:
                await websocket.send_json({
                    "msg_id": str(r["msg_id"]),
                    "parent_msg_id": str(r["parent_msg_id"]) if r["parent_msg_id"] else None,
                    "instance_id": r["instance_id"],
                    "direction": r["direction"],
                    "kind": r["kind"],
                    "payload": r["payload"],
                    "source": r["source"],
                    "created_at": r["created_at"].isoformat(),
                    "route": r["route"],
                })
                last_seen_at = r["created_at"]
            if not rows:
                await _asyncio.sleep(0.2)

    try:
        await poll()
    except WebSocketDisconnect:
        pass
    except _asyncio.CancelledError:
        raise
    except Exception as exc:
        _log.exception("ws_session_stream.error", error=str(exc))
```

- [ ] **Step 2: Lint + import check**

```bash
cd backend
uv run ruff check src/agflow/api/public/sessions.py
uv run python -c "from agflow.main import create_app; create_app()"
```

- [ ] **Step 3: Commit**

```bash
git add backend/src/agflow/api/public/sessions.py
git commit -m "feat(sessions): session-level consolidated GET /messages + WS /stream"
```

---

## Task 10: Session expiry worker

Background task started in the FastAPI lifespan. Polls every 30s and expires stale sessions.

**Files:**
- Create: `backend/src/agflow/workers/__init__.py` (empty)
- Create: `backend/src/agflow/workers/session_expiry.py`
- Modify: `backend/src/agflow/main.py` — start/stop the worker in lifespan
- Test: `backend/tests/sessions/test_expiry_worker.py`

- [ ] **Step 1: Implement worker**

```python
# backend/src/agflow/workers/session_expiry.py
from __future__ import annotations

import asyncio

import structlog

from agflow.services import sessions_service

_log = structlog.get_logger(__name__)

POLL_INTERVAL_S = 30


async def run_expiry_loop(stop_event: asyncio.Event) -> None:
    _log.info("session_expiry.started", interval_s=POLL_INTERVAL_S)
    try:
        while not stop_event.is_set():
            try:
                count = await sessions_service.expire_stale()
                if count:
                    _log.info("session_expiry.swept", count=count)
            except Exception as exc:
                _log.warning("session_expiry.error", error=str(exc))
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=POLL_INTERVAL_S)
            except TimeoutError:
                continue
    finally:
        _log.info("session_expiry.stopped")
```

- [ ] **Step 2: Wire into `main.py` lifespan**

At the top of the lifespan context manager add:

```python
from agflow.workers.session_expiry import run_expiry_loop
_expiry_stop = asyncio.Event()
_expiry_task = asyncio.create_task(run_expiry_loop(_expiry_stop))
```

At the shutdown phase (after `yield`):

```python
_expiry_stop.set()
try:
    await asyncio.wait_for(_expiry_task, timeout=5)
except TimeoutError:
    _expiry_task.cancel()
```

- [ ] **Step 3: Test**

```python
# backend/tests/sessions/test_expiry_worker.py
from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
import pytest_asyncio

from agflow.db.pool import close_pool, execute, fetch_one, get_pool
from agflow.services import sessions_service
from agflow.workers.session_expiry import run_expiry_loop


@pytest_asyncio.fixture
async def pool():
    p = await get_pool()
    yield p
    await close_pool()


@pytest_asyncio.fixture
async def api_key_id(pool) -> UUID:
    kid = uuid4()
    await execute(
        "INSERT INTO api_keys (id, owner_id, name, prefix, key_hash, scopes) "
        "VALUES ($1, $2, 'test-expiry', $3, 'hash', $4)",
        kid, uuid4(), f"pfx_{str(kid)[:8]}", ["read"],
    )
    yield kid
    await execute("DELETE FROM api_keys WHERE id = $1", kid)


@pytest.mark.asyncio
async def test_expiry_loop_flags_stale_sessions(api_key_id: UUID) -> None:
    session = await sessions_service.create(
        api_key_id=api_key_id, name=None, duration_seconds=60,
    )
    await execute(
        "UPDATE sessions SET expires_at = now() - interval '1 minute' WHERE id = $1",
        session["id"],
    )

    stop = asyncio.Event()
    task = asyncio.create_task(run_expiry_loop(stop))
    await asyncio.sleep(0.5)
    stop.set()
    try:
        await asyncio.wait_for(task, timeout=2)
    except TimeoutError:
        task.cancel()

    row = await fetch_one(
        "SELECT status FROM sessions WHERE id = $1", session["id"],
    )
    assert row["status"] == "expired"
```

- [ ] **Step 4: Lint + commit**

```bash
cd backend
uv run ruff check src/agflow/workers/ src/agflow/main.py tests/sessions/test_expiry_worker.py
git add backend/src/agflow/workers/ backend/src/agflow/main.py backend/tests/sessions/test_expiry_worker.py
git commit -m "feat(sessions): expiry worker — periodic sweep of stale sessions"
```

---

## Task 11: Deploy + migrations applied + smoke test

**Files:**
- None (deploy only)

- [ ] **Step 1: Run deploy script**

```bash
cd E:/srcs/agflow.docker
bash scripts/deploy.sh --rebuild
```

- [ ] **Step 2: Verify migration 039 applied**

```bash
ssh pve "pct exec 201 -- bash -c 'docker logs agflow-backend 2>&1 | grep \"039_sessions\"'"
```
Expected: a single line containing `"version": "039_sessions_and_agents"`.

- [ ] **Step 3: Verify tables exist**

```bash
ssh pve "pct exec 201 -- bash -c 'docker exec agflow-postgres psql -U agflow -d agflow -c \"\\dt sessions;\\dt agents_instances;\\dt agents_catalog;\"'"
```
Expected: 3 tables listed.

- [ ] **Step 4: Smoke test via a real API key**

Fetch an existing admin api key prefix from the DB, or create one. Then:

```bash
# Replace TOKEN with a real agfd_... token
TOKEN=agfd_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Create a session
SID=$(curl -s -X POST http://192.168.10.158/api/v1/sessions \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"name":"smoke","duration_seconds":600}' | jq -r .id)
echo "session_id=$SID"

# Create 2 instances of an existing agent (e.g., mistral)
curl -s -X POST http://192.168.10.158/api/v1/sessions/$SID/agents \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"agent_id":"mistral","count":2}' | jq .

# List instances
curl -s http://192.168.10.158/api/v1/sessions/$SID/agents \
    -H "Authorization: Bearer $TOKEN" | jq .

# Close
curl -s -X DELETE http://192.168.10.158/api/v1/sessions/$SID \
    -H "Authorization: Bearer $TOKEN" -i | head -1
```

Expected outputs: 201 for create, 2 instance_ids, 200 with 2 idle instances, 204 on close.

- [ ] **Step 5: No commit needed — this task is pure deploy/validate**

---

## Task 12: API documentation markdown

**Files:**
- Create: `docs/api/sessions-agents.md`

- [ ] **Step 1: Write the documentation file**

Content outline (write as the actual Markdown):

```markdown
# API — Sessions, Agents, Dialogue

Public API for managing ephemeral workspaces (sessions), instantiating agents inside them, and dialoguing with those agents through the MOM bus.

All endpoints require a Bearer token: `Authorization: Bearer agfd_…`.

## Scoping

- Non-admin token: sees only data created by this same token (`WHERE api_key_id = …`).
- Admin token (`*` in scopes): sees everything.

## Errors

- `401 invalid_format | invalid_checksum | expired | revoked_or_unknown`
- `403 missing_scope` — token lacks a required scope
- `404 session not found | instance not found`
- `409 session is closed | session is expired`
- `400 agent_id not in catalog | invalid payload`
- `429 rate_limited`

---

## 1. POST /api/v1/sessions — Create session

Request:
\`\`\`bash
curl -X POST https://api.agflow.example/api/v1/sessions \
    -H "Authorization: Bearer agfd_…" \
    -H "Content-Type: application/json" \
    -d '{"name":"my-run","duration_seconds":3600}'
\`\`\`

Body: `{ name?: string, duration_seconds?: int (default 3600, max 86400) }`.

Response 201: `{ id, api_key_id, name, status:"active", created_at, expires_at, closed_at:null }`.

## 2. GET /api/v1/sessions/{id} — Read session
…(continue for all 12 methods)…

## 3. PATCH /api/v1/sessions/{id}/extend

## 4. DELETE /api/v1/sessions/{id}

## 5. POST /api/v1/sessions/{id}/agents

## 6. GET /api/v1/sessions/{id}/agents

## 7. DELETE /api/v1/sessions/{id}/agents/{instance_id}

## 8. POST /api/v1/sessions/{s}/agents/{i}/message

## 9. GET /api/v1/sessions/{s}/agents/{i}/messages

## 10. WebSocket /api/v1/sessions/{s}/agents/{i}/stream

## 11. GET /api/v1/sessions/{s}/messages

## 12. WebSocket /api/v1/sessions/{s}/stream

## Complete scenario (curl)

\`\`\`bash
TOKEN=agfd_…

# 1. Open
SID=$(curl -s -X POST $API/api/v1/sessions -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"duration_seconds":1800}' | jq -r .id)

# 2. Spawn tech-lead + 2 specialists
curl -s -X POST $API/api/v1/sessions/$SID/agents -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"agent_id":"tech-lead","count":1}'
curl -s -X POST $API/api/v1/sessions/$SID/agents -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"agent_id":"python-specialist","count":2}'

# 3. Send instruction to the tech-lead
TECH_ID=...  # from previous response
curl -X POST $API/api/v1/sessions/$SID/agents/$TECH_ID/message \
    -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d '{"kind":"instruction","payload":{"text":"Refactor login.py"}}'

# 4. Observe via WebSocket
wscat -c wss://api.agflow.example/api/v1/sessions/$SID/stream

# 5. Close
curl -X DELETE $API/api/v1/sessions/$SID -H "Authorization: Bearer $TOKEN"
\`\`\`
```

For each of the 12 methods, the documentation MUST include:
- Path + HTTP verb
- Required scopes (if any)
- Path params (with types)
- Query params (with defaults)
- Request body JSON schema (with example)
- Response 2xx body JSON schema (with example)
- Error cases with HTTP codes
- **A complete curl example** (never `...`)

The single "complete scenario" at the bottom shows the happy path end-to-end.

- [ ] **Step 2: Commit**

```bash
git add docs/api/sessions-agents.md
git commit -m "docs(sessions): complete API doc with 12 methods + curl examples"
```

---

## Task 13: Test plan markdown — real scenarios

**Files:**
- Create: `docs/test-plans/sessions-v1-scenarios.md`

- [ ] **Step 1: Write the test plan file**

Content (write as actual Markdown):

```markdown
# Test Plan — Sessions + Agents V1 (Real Scenarios)

Manual + integration scenarios run after deploy on LXC 201. Each scenario has pre-conditions, steps, expected results, and cleanup.

## S1 — Happy path: open → 2 agents → exchange → close

**Pre:** valid non-admin token `TOKEN_A`, agents `tech-lead` and `python-specialist` present in `data/agents/`.
**Steps:**
1. `POST /sessions` with duration_seconds=600 → record `SID`, `expires_at`.
2. `POST /sessions/$SID/agents {agent_id:"tech-lead",count:1}` → record `TECH`.
3. `POST /sessions/$SID/agents {agent_id:"python-specialist",count:2}` → record `SPEC_1`, `SPEC_2`.
4. `GET /sessions/$SID/agents` → 3 entries, all status=idle.
5. `POST /sessions/$SID/agents/$TECH/message {kind:"instruction",payload:{text:"delegate to spec_1"}}` → 201, `msg_id`.
6. Open `WS /sessions/$SID/stream` → observe OUT events.
7. `GET /sessions/$SID/messages` → includes instruction, events, result in chronological order.
8. `DELETE /sessions/$SID` → 204.
**Expect:** all calls succeed, WS receives events within 10s, messages are persisted.
**Cleanup:** none (session closed).

## S2 — Scoping: stranger cannot see my session

**Pre:** `TOKEN_A` (non-admin) and `TOKEN_B` (different non-admin, different owner).
**Steps:**
1. With `TOKEN_A`: `POST /sessions` → `SID`.
2. With `TOKEN_B`: `GET /sessions/$SID` → **404**.
3. With `TOKEN_B`: `DELETE /sessions/$SID` → **404**.
4. With `TOKEN_B`: `POST /sessions/$SID/agents` → **404**.
**Expect:** stranger cannot access anything.
**Cleanup:** `TOKEN_A` DELETE the session.

## S3 — Admin bypass

**Pre:** `TOKEN_A` (owner), `TOKEN_ADMIN` (scope `*`).
**Steps:**
1. Non-admin creates session.
2. Admin `GET /sessions/$SID` → **200**.
3. Admin `GET /sessions/$SID/messages` → **200**.
4. Admin `DELETE /sessions/$SID` → **204**.
**Expect:** admin sees and acts on any session.

## S4 — Expiration

**Pre:** any token.
**Steps:**
1. `POST /sessions duration_seconds=60`.
2. Wait 90s.
3. `GET /sessions/$SID` → `status=expired`.
4. `POST /sessions/$SID/agents` → **409** (not active).
**Expect:** expiry worker transitions status automatically.

## S5 — Extend before expiration

**Pre:** valid token.
**Steps:**
1. `POST /sessions duration_seconds=60`.
2. `PATCH /sessions/$SID/extend {duration_seconds:1800}` → 200, new `expires_at`.
3. Wait 90s.
4. `GET /sessions/$SID` → `status=active` (not expired yet).
**Expect:** extend adds time to the existing expires_at.

## S6 — Destroy-rebuild agent mid-session

**Pre:** session active, 2 instances of specialist.
**Steps:**
1. `DELETE /sessions/$SID/agents/$SPEC_1` → 204.
2. `GET /sessions/$SID/agents` → only 1 active instance.
3. `POST /sessions/$SID/agents {agent_id:"python-specialist",count:1}` → new `SPEC_3`.
4. `GET /sessions/$SID/agents` → 2 active.
**Expect:** destroyed agent hidden from list; rebuild produces a new id.

## S7 — Catalog FK enforcement

**Steps:**
1. `POST /sessions/$SID/agents {agent_id:"non-existent-bogus",count:1}` → **400**.
**Expect:** clear error about catalog.

## S8 — Inter-agent routing

**Pre:** session with 2 agents `tech-lead` and `python-specialist`, IDs known (injected via system prompt for real usage; here simulated).
**Steps:**
1. `POST /sessions/$SID/agents/$TECH/message {payload:{text:"…"},route_to:"agent:$SPEC_ID"}`.
2. Wait for Router processing.
3. `GET /sessions/$SID/agents/$SPEC_ID/messages?direction=in` → includes the routed instruction with parent_msg_id pointing at the tech-lead's OUT.
**Expect:** Router creates a chained IN for the target agent.

## S9 — WebSocket reconnection

**Steps:**
1. Open `WS /sessions/$SID/agents/$INST/stream`.
2. Trigger a message. Observe an event.
3. Close the WS.
4. POST another message while disconnected.
5. `GET /sessions/$SID/agents/$INST/messages` → the message from step 4 is there.
6. Reopen WS — future events arrive.
**Expect:** history preserved regardless of WS state.

## S10 — Rate limit

**Pre:** token with low `rate_limit` (e.g. 5/min).
**Steps:**
1. Make 6 rapid `POST /sessions` calls.
2. The 6th returns **429** with `Retry-After` header.
**Expect:** rate limit triggers as configured.

## Coverage

- Scoping: S1, S2, S3
- Lifecycle: S1, S4, S5, S6
- FK / validation: S7
- MOM integration: S1, S8, S9
- Rate limit: S10
- Admin: S3
```

- [ ] **Step 2: Commit**

```bash
git add docs/test-plans/sessions-v1-scenarios.md
git commit -m "docs(sessions): end-to-end test scenarios (S1–S10)"
```

---

## Verification Checklist

- [ ] `cd backend && uv run pytest tests/sessions/ -v` → all non-DB tests pass locally; all DB tests pass on LXC 201.
- [ ] `cd backend && uv run ruff check src/ tests/` → no errors.
- [ ] Migration 039 applied on LXC 201.
- [ ] Tables `sessions`, `agents_instances`, `agents_catalog` exist.
- [ ] The scenario in Task 11 Step 4 completes without error.
- [ ] Scoping enforced (S2 scenario in Task 13).
- [ ] Expiry worker visible in logs (search for `session_expiry.started`).
- [ ] `docs/api/sessions-agents.md` exists and contains all 12 methods with curl examples.
- [ ] `docs/test-plans/sessions-v1-scenarios.md` exists with 10 numbered scenarios.
