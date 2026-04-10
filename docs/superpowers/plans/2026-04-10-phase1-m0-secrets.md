# agflow.docker Phase 1 — Module 0 (Secrets) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Module 0 (Secrets) — CRUD encrypted secrets stored via PostgreSQL `pgcrypto`, masked-by-default UI with temporary reveal, test endpoint for LLM keys, and the `resolve_env()` API used by future modules (M1/M3/M4) to assemble container `.env` files.

**Architecture:** Backend exposes `/api/admin/secrets/*` admin routes. Values are encrypted at rest with `pgp_sym_encrypt` using `SECRETS_MASTER_KEY` from env (never in the DB). List endpoints never return plaintext — only a dedicated `reveal` endpoint returns decrypted values (audit-logged). Frontend uses a single React Query-powered `SecretsPage` with a `SecretForm` modal for create/edit, a `RevealButton` that auto-hides after 10s, and a `TestKeyButton` that calls the backend which in turn hits the LLM provider's API. The existing `StatusIndicator` component (🔴🟠🟢) is reused by callers of `GET /api/admin/secrets/resolve-status?var_names=A,B,C` (preview API for future modules).

**Tech Stack:** Backend — FastAPI, asyncpg, pgcrypto (pgp_sym_encrypt/decrypt), Pydantic v2, httpx (for provider probes), structlog, pytest. Frontend — React 18 + TS strict, @tanstack/react-query, axios, i18next, Vitest + React Testing Library.

---

## Context

Phase 0 bootstrapped the monorepo and left us with: working FastAPI backend with JWT admin auth, PostgreSQL 16 + pgcrypto extension (already enabled by `001_init.sql`), asyncpg pool + migration runner, React SPA with login/home, `StatusIndicator` component. Module 0 is the first real product feature and the foundation for every subsequent module — every agent, every MCP, every Dockerfile parameter will reference secrets by alias (env var name). Getting the encryption, CRUD, and resolver right now saves rework later.

**What is NOT in this phase:**
- **Per-agent scope** — the `agent_id` column exists in the schema but cannot be set from the UI in Phase 1 (no agents exist until M4). Scope is implicitly `global` for everything created in Phase 1.
- **Used-by tracking** — `used_by` column in the UI returns an empty array for now. Will be wired to M1/M3/M4 when those modules land.
- **Rotation / history** — no versioning of values. Edit overwrites.
- **Multi-LLM test helpers** — only Anthropic and OpenAI are implemented in `test_key`. Others (Mistral, Google, Groq, etc.) return `{"supported": false}` for now.

---

## File Structure

### Files created

**Backend (`backend/`):**
- `migrations/002_secrets.sql` — `secrets` table, constraints, index
- `src/agflow/services/__init__.py` — (package marker)
- `src/agflow/services/secrets_service.py` — CRUD + encryption helpers + resolver
- `src/agflow/services/llm_key_tester.py` — provider-specific probe functions (Anthropic, OpenAI; others stubbed)
- `src/agflow/schemas/secrets.py` — Pydantic DTOs
- `src/agflow/api/admin/secrets.py` — router `/api/admin/secrets`
- `tests/test_secrets_service.py` — unit tests for encryption + CRUD + resolve
- `tests/test_secrets_endpoint.py` — integration tests for all routes
- `tests/test_llm_key_tester.py` — test for provider probe with mocked httpx

**Backend (modified):**
- `src/agflow/config.py` — add `secrets_master_key: str` setting
- `src/agflow/main.py` — register secrets router
- `tests/conftest.py` — seed `SECRETS_MASTER_KEY` env var

**Frontend (`frontend/`):**
- `src/pages/SecretsPage.tsx` — list + table + add button
- `src/components/SecretForm.tsx` — create/edit modal
- `src/components/RevealButton.tsx` — reveal value for 10s then auto-hide
- `src/components/TestKeyButton.tsx` — trigger test + show result
- `src/hooks/useSecrets.ts` — React Query hooks
- `src/lib/secretsApi.ts` — typed API wrappers
- `tests/pages/SecretsPage.test.tsx`
- `tests/components/SecretForm.test.tsx`
- `tests/components/RevealButton.test.tsx`
- `tests/hooks/useSecrets.test.tsx`

**Frontend (modified):**
- `src/App.tsx` — add `/secrets` route (protected)
- `src/pages/HomePage.tsx` — add a nav link to `/secrets`
- `src/i18n/fr.json` / `src/i18n/en.json` — add secrets translations

**Root (modified):**
- `.env.example` — document `SECRETS_MASTER_KEY`
- `.env` (local only, not committed) — set real master key before redeploying

---

## Data model

### `secrets` table (migration `002_secrets.sql`)

```sql
CREATE TABLE IF NOT EXISTS secrets (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    var_name        TEXT NOT NULL,
    value_encrypted BYTEA NOT NULL,
    scope           TEXT NOT NULL DEFAULT 'global'
                    CHECK (scope IN ('global', 'agent')),
    agent_id        UUID NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (var_name, scope, agent_id)
);

CREATE INDEX IF NOT EXISTS idx_secrets_var_name ON secrets(var_name);
```

### Encryption strategy

- All writes use `pgp_sym_encrypt(plaintext, $1)` where `$1` is `SECRETS_MASTER_KEY` from env.
- All reads use `pgp_sym_decrypt(value_encrypted, $1)`.
- The master key **never** touches the DB. If it's lost → all secrets are unrecoverable (documented in `.env.example`).
- `value_encrypted` is a `BYTEA`, not text — asyncpg returns `bytes`.

### API shape

| Endpoint | Method | Body / Params | Returns |
|---|---|---|---|
| `/api/admin/secrets` | GET | — | list of `SecretSummary` (no plaintext) |
| `/api/admin/secrets` | POST | `SecretCreate` | `SecretSummary` |
| `/api/admin/secrets/{id}` | PUT | `SecretUpdate` | `SecretSummary` |
| `/api/admin/secrets/{id}` | DELETE | — | 204 |
| `/api/admin/secrets/{id}/reveal` | GET | — | `SecretReveal` (plaintext, audit-logged) |
| `/api/admin/secrets/{id}/test` | POST | — | `SecretTestResult` |
| `/api/admin/secrets/resolve-status` | GET | `?var_names=A,B,C` | `{A: "ok"|"empty"|"missing", …}` |

All endpoints require `Authorization: Bearer <jwt>` (uses existing `require_admin` dep from Phase 0).

---

## Tasks

### Task 1: Add `SECRETS_MASTER_KEY` to config + test

**Files:**
- Modify: `backend/src/agflow/config.py`
- Modify: `backend/tests/conftest.py`
- Modify: `backend/tests/test_config.py`

- [ ] **Step 1: Write failing test for new setting**

Edit `backend/tests/test_config.py`, add at the end:

```python
def test_settings_requires_secrets_master_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/test")
    monkeypatch.setenv("JWT_SECRET", "x")
    monkeypatch.setenv("ADMIN_EMAIL", "a@b.c")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", "x")
    monkeypatch.setenv("SECRETS_MASTER_KEY", "test-master-key-phrase-32chars-ok")

    settings = Settings()
    assert settings.secrets_master_key == "test-master-key-phrase-32chars-ok"
```

- [ ] **Step 2: Run the test — expect it to fail**

Run: `cd backend && uv run python -m pytest tests/test_config.py::test_settings_requires_secrets_master_key -v`
Expected: `AttributeError: 'Settings' object has no attribute 'secrets_master_key'`.

- [ ] **Step 3: Add the field in `config.py`**

Edit `backend/src/agflow/config.py`, in class `Settings`, after `admin_password_hash: str`:

```python
    secrets_master_key: str
```

- [ ] **Step 4: Update `conftest.py` to seed the env var**

Edit `backend/tests/conftest.py`, add before the `from agflow.main import create_app` import:

```python
os.environ.setdefault("SECRETS_MASTER_KEY", "test-master-key-phrase-32chars-ok")
```

- [ ] **Step 5: Run the full suite**

Run: `cd backend && uv run python -m pytest -q`
Expected: 15 passed (14 from Phase 0 + 1 new).

- [ ] **Step 6: Commit**

```bash
git add backend/src/agflow/config.py backend/tests/conftest.py backend/tests/test_config.py
git commit -m "feat(m0): add SECRETS_MASTER_KEY setting"
```

---

### Task 2: Write migration `002_secrets.sql` + test it applies

**Files:**
- Create: `backend/migrations/002_secrets.sql`
- Modify: `backend/tests/test_migrations.py`

- [ ] **Step 1: Write the migration file**

Create `backend/migrations/002_secrets.sql`:

```sql
-- 002_secrets — Module 0 secrets table
CREATE TABLE IF NOT EXISTS secrets (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    var_name        TEXT NOT NULL,
    value_encrypted BYTEA NOT NULL,
    scope           TEXT NOT NULL DEFAULT 'global'
                    CHECK (scope IN ('global', 'agent')),
    agent_id        UUID NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (var_name, scope, agent_id)
);

CREATE INDEX IF NOT EXISTS idx_secrets_var_name ON secrets(var_name);
```

- [ ] **Step 2: Write a failing test for the new migration**

Edit `backend/tests/test_migrations.py`, add at the end:

```python
@pytest.mark.asyncio
async def test_migration_002_creates_secrets_table() -> None:
    await execute("DROP TABLE IF EXISTS secrets CASCADE")
    await execute("DROP TABLE IF EXISTS schema_migrations CASCADE")

    applied = await run_migrations(_MIGRATIONS_DIR)

    assert "001_init" in applied
    assert "002_secrets" in applied

    row = await fetch_one(
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_name = 'secrets' AND column_name = 'value_encrypted'
        """
    )
    assert row is not None
    assert row["data_type"] == "bytea"
    await close_pool()
```

- [ ] **Step 3: Run — should PASS (migration runner picks up new file automatically)**

Run: `cd backend && uv run python -m pytest tests/test_migrations.py -v`
Expected: 3 passed (the 2 existing + the new one).

- [ ] **Step 4: Apply migration on LXC 201 test DB**

Run: `cd backend && DATABASE_URL="postgresql://agflow:agflow_dev@192.168.10.82:5432/agflow" uv run python -m agflow.db.migrations`
Expected: log shows `applied=['002_secrets']` (or empty if previous test already applied).

- [ ] **Step 5: Verify schema directly**

Run:
```bash
ssh pve "pct exec 201 -- docker exec agflow-postgres psql -U agflow -d agflow -c '\d secrets'"
```
Expected: table listing showing `id`, `var_name`, `value_encrypted`, `scope`, `agent_id`, `created_at`, `updated_at`.

- [ ] **Step 6: Commit**

```bash
git add backend/migrations/002_secrets.sql backend/tests/test_migrations.py
git commit -m "feat(m0): migration 002_secrets — encrypted secrets table"
```

---

### Task 3: Pydantic schemas for secrets

**Files:**
- Create: `backend/src/agflow/schemas/secrets.py`

- [ ] **Step 1: Create the schemas file**

Create `backend/src/agflow/schemas/secrets.py`:

```python
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

SCOPE_VALUES = ("global", "agent")
Scope = Literal["global", "agent"]


class SecretCreate(BaseModel):
    var_name: str = Field(min_length=1, max_length=128)
    value: str = Field(min_length=1)
    scope: Scope = "global"

    @field_validator("var_name")
    @classmethod
    def _upper_snake_case(cls, v: str) -> str:
        v = v.strip()
        if not v.replace("_", "").isalnum():
            raise ValueError(
                "var_name must contain only alphanumeric characters and underscores"
            )
        return v.upper()


class SecretUpdate(BaseModel):
    value: str | None = Field(default=None, min_length=1)
    scope: Scope | None = None


class SecretSummary(BaseModel):
    id: UUID
    var_name: str
    scope: Scope
    created_at: datetime
    updated_at: datetime
    used_by: list[str] = Field(default_factory=list)


class SecretReveal(BaseModel):
    id: UUID
    var_name: str
    value: str


class SecretTestResult(BaseModel):
    supported: bool
    ok: bool
    detail: str


class ResolveStatusItem(BaseModel):
    status: Literal["ok", "empty", "missing"]
```

- [ ] **Step 2: Quick import sanity check**

Run: `cd backend && uv run python -c "from agflow.schemas.secrets import SecretCreate; print(SecretCreate(var_name='anthropic_api_key', value='x').var_name)"`
Expected: `ANTHROPIC_API_KEY` (validator upper-cases).

- [ ] **Step 3: Commit**

```bash
git add backend/src/agflow/schemas/secrets.py
git commit -m "feat(m0): Pydantic schemas for secrets DTOs"
```

---

### Task 4: `secrets_service.py` — CRUD + pgcrypto encryption (TDD)

**Files:**
- Create: `backend/src/agflow/services/__init__.py`
- Create: `backend/src/agflow/services/secrets_service.py`
- Create: `backend/tests/test_secrets_service.py`

- [ ] **Step 1: Write the failing test file**

Create `backend/tests/test_secrets_service.py`:

```python
from __future__ import annotations

import os
import uuid

import pytest

os.environ["DATABASE_URL"] = "postgresql://agflow:agflow_dev@192.168.10.82:5432/agflow"
os.environ["SECRETS_MASTER_KEY"] = "test-master-key-phrase-32chars-ok"

from agflow.db.migrations import run_migrations
from agflow.db.pool import close_pool, execute
from agflow.services import secrets_service
from pathlib import Path


@pytest.fixture(autouse=True)
async def _clean_secrets_table() -> None:
    await execute("DROP TABLE IF EXISTS secrets CASCADE")
    await execute("DROP TABLE IF EXISTS schema_migrations CASCADE")
    await run_migrations(Path(__file__).parent.parent / "migrations")
    yield
    await close_pool()


@pytest.mark.asyncio
async def test_create_secret_encrypts_value() -> None:
    summary = await secrets_service.create(var_name="ANTHROPIC_API_KEY", value="sk-ant-xyz")

    assert summary.var_name == "ANTHROPIC_API_KEY"
    assert summary.scope == "global"
    assert summary.id is not None

    # Raw DB row must contain BYTES, not plaintext
    from agflow.db.pool import fetch_one
    row = await fetch_one("SELECT value_encrypted FROM secrets WHERE id = $1", summary.id)
    assert row is not None
    assert b"sk-ant-xyz" not in row["value_encrypted"]


@pytest.mark.asyncio
async def test_reveal_decrypts_value() -> None:
    summary = await secrets_service.create(var_name="OPENAI_API_KEY", value="sk-openai-abc")

    revealed = await secrets_service.reveal(summary.id)
    assert revealed.value == "sk-openai-abc"
    assert revealed.var_name == "OPENAI_API_KEY"


@pytest.mark.asyncio
async def test_list_returns_summaries_without_values() -> None:
    await secrets_service.create(var_name="KEY_A", value="value-a")
    await secrets_service.create(var_name="KEY_B", value="value-b")

    items = await secrets_service.list_all()
    names = [s.var_name for s in items]
    assert "KEY_A" in names
    assert "KEY_B" in names

    # Summaries never include plaintext
    for item in items:
        assert not hasattr(item, "value")


@pytest.mark.asyncio
async def test_update_replaces_value() -> None:
    summary = await secrets_service.create(var_name="KEY_UPDATE", value="old")

    await secrets_service.update(summary.id, value="new")

    revealed = await secrets_service.reveal(summary.id)
    assert revealed.value == "new"


@pytest.mark.asyncio
async def test_delete_removes_the_row() -> None:
    summary = await secrets_service.create(var_name="KEY_DEL", value="x")

    await secrets_service.delete(summary.id)

    items = await secrets_service.list_all()
    assert all(s.id != summary.id for s in items)


@pytest.mark.asyncio
async def test_create_rejects_duplicate_var_name_in_same_scope() -> None:
    await secrets_service.create(var_name="DUPKEY", value="a")

    with pytest.raises(secrets_service.DuplicateSecretError):
        await secrets_service.create(var_name="DUPKEY", value="b")


@pytest.mark.asyncio
async def test_reveal_missing_raises() -> None:
    with pytest.raises(secrets_service.SecretNotFoundError):
        await secrets_service.reveal(uuid.uuid4())


@pytest.mark.asyncio
async def test_resolve_env_returns_dict() -> None:
    await secrets_service.create(var_name="ANTHROPIC_API_KEY", value="sk-ant")
    await secrets_service.create(var_name="OPENAI_API_KEY", value="sk-openai")

    env = await secrets_service.resolve_env(["ANTHROPIC_API_KEY", "OPENAI_API_KEY"])
    assert env == {"ANTHROPIC_API_KEY": "sk-ant", "OPENAI_API_KEY": "sk-openai"}


@pytest.mark.asyncio
async def test_resolve_env_raises_on_missing() -> None:
    with pytest.raises(secrets_service.SecretNotFoundError) as exc:
        await secrets_service.resolve_env(["MISSING_KEY"])
    assert "MISSING_KEY" in str(exc.value)


@pytest.mark.asyncio
async def test_resolve_status_returns_per_var() -> None:
    await secrets_service.create(var_name="KEY_OK", value="value")
    await secrets_service.create(var_name="KEY_EMPTY", value=" ")  # whitespace = empty

    status = await secrets_service.resolve_status(["KEY_OK", "KEY_EMPTY", "KEY_MISSING"])
    assert status["KEY_OK"] == "ok"
    assert status["KEY_EMPTY"] == "empty"
    assert status["KEY_MISSING"] == "missing"
```

- [ ] **Step 2: Run — expect import/module error**

Run: `cd backend && uv run python -m pytest tests/test_secrets_service.py -v`
Expected: `ModuleNotFoundError: No module named 'agflow.services'` (or similar).

- [ ] **Step 3: Create the services package**

Create `backend/src/agflow/services/__init__.py`:

```python
```

(empty file, just a package marker)

- [ ] **Step 4: Implement `secrets_service.py`**

Create `backend/src/agflow/services/secrets_service.py`:

```python
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

import asyncpg
import structlog

from agflow.config import get_settings
from agflow.db.pool import fetch_all, fetch_one, get_pool
from agflow.schemas.secrets import (
    ResolveStatusItem,
    Scope,
    SecretReveal,
    SecretSummary,
)

_log = structlog.get_logger(__name__)


class SecretNotFoundError(Exception):
    pass


class DuplicateSecretError(Exception):
    pass


async def create(
    var_name: str,
    value: str,
    scope: Scope = "global",
    agent_id: UUID | None = None,
) -> SecretSummary:
    master = get_settings().secrets_master_key
    try:
        row = await fetch_one(
            """
            INSERT INTO secrets (var_name, value_encrypted, scope, agent_id)
            VALUES ($1, pgp_sym_encrypt($2, $3), $4, $5)
            RETURNING id, var_name, scope, created_at, updated_at
            """,
            var_name,
            value,
            master,
            scope,
            agent_id,
        )
    except asyncpg.UniqueViolationError as exc:
        raise DuplicateSecretError(
            f"Secret '{var_name}' already exists in scope '{scope}'"
        ) from exc
    assert row is not None
    _log.info("secrets.create", var_name=var_name, scope=scope)
    return SecretSummary(**row, used_by=[])


async def list_all() -> list[SecretSummary]:
    rows = await fetch_all(
        """
        SELECT id, var_name, scope, created_at, updated_at
        FROM secrets
        ORDER BY var_name ASC
        """
    )
    return [SecretSummary(**r, used_by=[]) for r in rows]


async def get_by_id(secret_id: UUID) -> SecretSummary:
    row = await fetch_one(
        "SELECT id, var_name, scope, created_at, updated_at FROM secrets WHERE id = $1",
        secret_id,
    )
    if row is None:
        raise SecretNotFoundError(f"Secret {secret_id} not found")
    return SecretSummary(**row, used_by=[])


async def reveal(secret_id: UUID) -> SecretReveal:
    master = get_settings().secrets_master_key
    row = await fetch_one(
        """
        SELECT id, var_name, pgp_sym_decrypt(value_encrypted, $2) AS value
        FROM secrets
        WHERE id = $1
        """,
        secret_id,
        master,
    )
    if row is None:
        raise SecretNotFoundError(f"Secret {secret_id} not found")
    _log.info("secrets.reveal", secret_id=str(secret_id), var_name=row["var_name"])
    return SecretReveal(id=row["id"], var_name=row["var_name"], value=row["value"])


async def update(
    secret_id: UUID,
    value: str | None = None,
    scope: Scope | None = None,
) -> SecretSummary:
    master = get_settings().secrets_master_key
    sets: list[str] = []
    args: list[object] = []
    idx = 1
    if value is not None:
        sets.append(f"value_encrypted = pgp_sym_encrypt(${idx}, ${idx + 1})")
        args.extend([value, master])
        idx += 2
    if scope is not None:
        sets.append(f"scope = ${idx}")
        args.append(scope)
        idx += 1
    if not sets:
        return await get_by_id(secret_id)
    sets.append("updated_at = NOW()")
    args.append(secret_id)
    query = f"""
        UPDATE secrets SET {", ".join(sets)}
        WHERE id = ${idx}
        RETURNING id, var_name, scope, created_at, updated_at
    """
    row = await fetch_one(query, *args)
    if row is None:
        raise SecretNotFoundError(f"Secret {secret_id} not found")
    _log.info("secrets.update", secret_id=str(secret_id))
    return SecretSummary(**row, used_by=[])


async def delete(secret_id: UUID) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM secrets WHERE id = $1", secret_id)
    if result == "DELETE 0":
        raise SecretNotFoundError(f"Secret {secret_id} not found")
    _log.info("secrets.delete", secret_id=str(secret_id))


async def resolve_env(var_names: list[str]) -> dict[str, str]:
    """Resolve alias names to their plaintext values.

    Raises SecretNotFoundError listing all missing names.
    """
    master = get_settings().secrets_master_key
    rows = await fetch_all(
        """
        SELECT var_name, pgp_sym_decrypt(value_encrypted, $2) AS value
        FROM secrets
        WHERE var_name = ANY($1::text[]) AND scope = 'global'
        """,
        var_names,
        master,
    )
    resolved = {r["var_name"]: r["value"] for r in rows}
    missing = [n for n in var_names if n not in resolved]
    if missing:
        raise SecretNotFoundError(
            f"Missing secrets: {', '.join(missing)}"
        )
    return resolved


async def resolve_status(
    var_names: list[str],
) -> dict[str, Literal["ok", "empty", "missing"]]:
    """Return status for each requested variable (for visual indicators 🔴🟠🟢)."""
    master = get_settings().secrets_master_key
    rows = await fetch_all(
        """
        SELECT var_name, pgp_sym_decrypt(value_encrypted, $2) AS value
        FROM secrets
        WHERE var_name = ANY($1::text[]) AND scope = 'global'
        """,
        var_names,
        master,
    )
    present = {r["var_name"]: r["value"] for r in rows}
    result: dict[str, Literal["ok", "empty", "missing"]] = {}
    for name in var_names:
        if name not in present:
            result[name] = "missing"
        elif not present[name].strip():
            result[name] = "empty"
        else:
            result[name] = "ok"
    return result
```

- [ ] **Step 5: Run — most tests should pass**

Run: `cd backend && uv run python -m pytest tests/test_secrets_service.py -v`
Expected: 10 passed. If any fail, read the traceback and fix — **do not move on with red tests**.

- [ ] **Step 6: Commit**

```bash
git add backend/src/agflow/services/__init__.py backend/src/agflow/services/secrets_service.py backend/tests/test_secrets_service.py
git commit -m "feat(m0): secrets_service with pgcrypto encryption + tests"
```

---

### Task 5: `llm_key_tester.py` — provider probes (TDD)

**Files:**
- Create: `backend/src/agflow/services/llm_key_tester.py`
- Create: `backend/tests/test_llm_key_tester.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_llm_key_tester.py`:

```python
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from agflow.services.llm_key_tester import test_key


@pytest.mark.asyncio
async def test_unknown_var_name_returns_unsupported() -> None:
    result = await test_key(var_name="RANDOM_TOKEN", value="xxx")
    assert result.supported is False
    assert result.ok is False


@pytest.mark.asyncio
async def test_anthropic_success() -> None:
    mock_response = AsyncMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json = AsyncMock(return_value={"data": []})
    mock_response.raise_for_status = lambda: None

    with patch("agflow.services.llm_key_tester.httpx.AsyncClient") as mock_client:
        instance = AsyncMock()
        instance.__aenter__.return_value = instance
        instance.get = AsyncMock(return_value=mock_response)
        mock_client.return_value = instance

        result = await test_key(var_name="ANTHROPIC_API_KEY", value="sk-ant-valid")

    assert result.supported is True
    assert result.ok is True
    assert "200" in result.detail or "ok" in result.detail.lower()


@pytest.mark.asyncio
async def test_anthropic_unauthorized() -> None:
    mock_response = AsyncMock(spec=httpx.Response)
    mock_response.status_code = 401
    mock_response.text = "Unauthorized"

    with patch("agflow.services.llm_key_tester.httpx.AsyncClient") as mock_client:
        instance = AsyncMock()
        instance.__aenter__.return_value = instance
        instance.get = AsyncMock(return_value=mock_response)
        mock_client.return_value = instance

        result = await test_key(var_name="ANTHROPIC_API_KEY", value="sk-ant-bad")

    assert result.supported is True
    assert result.ok is False
    assert "401" in result.detail
```

- [ ] **Step 2: Run — expect ModuleNotFoundError**

Run: `cd backend && uv run python -m pytest tests/test_llm_key_tester.py -v`
Expected: module not found error.

- [ ] **Step 3: Implement `llm_key_tester.py`**

Create `backend/src/agflow/services/llm_key_tester.py`:

```python
from __future__ import annotations

import httpx
import structlog

from agflow.schemas.secrets import SecretTestResult

_log = structlog.get_logger(__name__)
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


async def test_key(var_name: str, value: str) -> SecretTestResult:
    """Probe a provider's API to validate a key."""
    probe = _PROBES.get(var_name)
    if probe is None:
        return SecretTestResult(
            supported=False,
            ok=False,
            detail=f"No test probe implemented for {var_name}",
        )
    return await probe(value)


async def _probe_anthropic(key: str) -> SecretTestResult:
    url = "https://api.anthropic.com/v1/models"
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        _log.warning("llm_key_tester.anthropic.error", error=str(exc))
        return SecretTestResult(
            supported=True, ok=False, detail=f"Connection error: {exc}"
        )
    if response.status_code == 200:
        return SecretTestResult(supported=True, ok=True, detail="200 ok")
    return SecretTestResult(
        supported=True,
        ok=False,
        detail=f"HTTP {response.status_code}: {response.text[:200]}",
    )


async def _probe_openai(key: str) -> SecretTestResult:
    url = "https://api.openai.com/v1/models"
    headers = {"Authorization": f"Bearer {key}"}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        return SecretTestResult(
            supported=True, ok=False, detail=f"Connection error: {exc}"
        )
    if response.status_code == 200:
        return SecretTestResult(supported=True, ok=True, detail="200 ok")
    return SecretTestResult(
        supported=True,
        ok=False,
        detail=f"HTTP {response.status_code}: {response.text[:200]}",
    )


_PROBES = {
    "ANTHROPIC_API_KEY": _probe_anthropic,
    "OPENAI_API_KEY": _probe_openai,
}
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && uv run python -m pytest tests/test_llm_key_tester.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/agflow/services/llm_key_tester.py backend/tests/test_llm_key_tester.py
git commit -m "feat(m0): llm_key_tester with Anthropic + OpenAI probes"
```

---

### Task 6: Admin secrets router (CRUD + reveal + test + resolve-status)

**Files:**
- Create: `backend/src/agflow/api/admin/secrets.py`
- Create: `backend/tests/test_secrets_endpoint.py`
- Modify: `backend/src/agflow/main.py`

- [ ] **Step 1: Write failing endpoint tests**

Create `backend/tests/test_secrets_endpoint.py`:

```python
from __future__ import annotations

from fastapi.testclient import TestClient


def _auth_header(client: TestClient) -> dict[str, str]:
    res = client.post(
        "/api/admin/auth/login",
        json={"email": "admin@example.com", "password": "correct-password"},
    )
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_list_requires_auth(client: TestClient) -> None:
    res = client.get("/api/admin/secrets")
    assert res.status_code == 401


def test_create_list_delete_secret(client: TestClient) -> None:
    headers = _auth_header(client)

    # Create
    create_res = client.post(
        "/api/admin/secrets",
        headers=headers,
        json={"var_name": "test_key_e2e", "value": "abc123", "scope": "global"},
    )
    assert create_res.status_code == 201, create_res.text
    body = create_res.json()
    assert body["var_name"] == "TEST_KEY_E2E"
    assert "value" not in body
    secret_id = body["id"]

    # List includes it
    list_res = client.get("/api/admin/secrets", headers=headers)
    assert list_res.status_code == 200
    names = [s["var_name"] for s in list_res.json()]
    assert "TEST_KEY_E2E" in names

    # Reveal returns plaintext
    reveal_res = client.get(f"/api/admin/secrets/{secret_id}/reveal", headers=headers)
    assert reveal_res.status_code == 200
    assert reveal_res.json()["value"] == "abc123"

    # Delete
    del_res = client.delete(f"/api/admin/secrets/{secret_id}", headers=headers)
    assert del_res.status_code == 204

    # List no longer includes it
    list_res2 = client.get("/api/admin/secrets", headers=headers)
    assert "TEST_KEY_E2E" not in [s["var_name"] for s in list_res2.json()]


def test_update_replaces_value(client: TestClient) -> None:
    headers = _auth_header(client)

    create_res = client.post(
        "/api/admin/secrets",
        headers=headers,
        json={"var_name": "update_test", "value": "old"},
    )
    secret_id = create_res.json()["id"]

    update_res = client.put(
        f"/api/admin/secrets/{secret_id}",
        headers=headers,
        json={"value": "new"},
    )
    assert update_res.status_code == 200

    reveal = client.get(f"/api/admin/secrets/{secret_id}/reveal", headers=headers)
    assert reveal.json()["value"] == "new"

    client.delete(f"/api/admin/secrets/{secret_id}", headers=headers)


def test_resolve_status(client: TestClient) -> None:
    headers = _auth_header(client)

    client.post(
        "/api/admin/secrets",
        headers=headers,
        json={"var_name": "resolve_ok", "value": "value"},
    )
    client.post(
        "/api/admin/secrets",
        headers=headers,
        json={"var_name": "resolve_empty", "value": " "},
    )

    res = client.get(
        "/api/admin/secrets/resolve-status",
        headers=headers,
        params={"var_names": "RESOLVE_OK,RESOLVE_EMPTY,RESOLVE_MISSING"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["RESOLVE_OK"] == "ok"
    assert data["RESOLVE_EMPTY"] == "empty"
    assert data["RESOLVE_MISSING"] == "missing"

    # Cleanup
    list_res = client.get("/api/admin/secrets", headers=headers)
    for s in list_res.json():
        if s["var_name"].startswith("RESOLVE_"):
            client.delete(f"/api/admin/secrets/{s['id']}", headers=headers)


def test_create_rejects_duplicate(client: TestClient) -> None:
    headers = _auth_header(client)

    client.post(
        "/api/admin/secrets",
        headers=headers,
        json={"var_name": "dup_test", "value": "a"},
    )
    res = client.post(
        "/api/admin/secrets",
        headers=headers,
        json={"var_name": "dup_test", "value": "b"},
    )
    assert res.status_code == 409

    # Cleanup
    list_res = client.get("/api/admin/secrets", headers=headers)
    for s in list_res.json():
        if s["var_name"] == "DUP_TEST":
            client.delete(f"/api/admin/secrets/{s['id']}", headers=headers)
```

- [ ] **Step 2: Run — expect 404 on all endpoints**

Run: `cd backend && uv run python -m pytest tests/test_secrets_endpoint.py -v`
Expected: many failures, mostly 404 Not Found.

- [ ] **Step 3: Implement the router**

Create `backend/src/agflow/api/admin/secrets.py`:

```python
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from agflow.auth.dependencies import require_admin
from agflow.schemas.secrets import (
    SecretCreate,
    SecretReveal,
    SecretSummary,
    SecretTestResult,
    SecretUpdate,
)
from agflow.services import secrets_service
from agflow.services.llm_key_tester import test_key

router = APIRouter(
    prefix="/api/admin/secrets",
    tags=["admin-secrets"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[SecretSummary])
async def list_secrets() -> list[SecretSummary]:
    return await secrets_service.list_all()


@router.post(
    "",
    response_model=SecretSummary,
    status_code=status.HTTP_201_CREATED,
)
async def create_secret(payload: SecretCreate) -> SecretSummary:
    try:
        return await secrets_service.create(
            var_name=payload.var_name,
            value=payload.value,
            scope=payload.scope,
        )
    except secrets_service.DuplicateSecretError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.put("/{secret_id}", response_model=SecretSummary)
async def update_secret(secret_id: UUID, payload: SecretUpdate) -> SecretSummary:
    try:
        return await secrets_service.update(
            secret_id, value=payload.value, scope=payload.scope
        )
    except secrets_service.SecretNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{secret_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_secret(secret_id: UUID) -> None:
    try:
        await secrets_service.delete(secret_id)
    except secrets_service.SecretNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{secret_id}/reveal", response_model=SecretReveal)
async def reveal_secret(secret_id: UUID) -> SecretReveal:
    try:
        return await secrets_service.reveal(secret_id)
    except secrets_service.SecretNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{secret_id}/test", response_model=SecretTestResult)
async def test_secret(secret_id: UUID) -> SecretTestResult:
    try:
        revealed = await secrets_service.reveal(secret_id)
    except secrets_service.SecretNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return await test_key(var_name=revealed.var_name, value=revealed.value)


@router.get("/resolve-status")
async def resolve_status(
    var_names: str = Query(..., description="Comma-separated list of var names"),
) -> dict[str, str]:
    names = [n.strip().upper() for n in var_names.split(",") if n.strip()]
    return await secrets_service.resolve_status(names)
```

- [ ] **Step 4: Register the router in `main.py`**

Edit `backend/src/agflow/main.py`, add import after `admin_auth_router`:

```python
from agflow.api.admin.secrets import router as admin_secrets_router
```

And in `create_app()`, add `app.include_router(admin_secrets_router)` after `app.include_router(admin_auth_router)`.

- [ ] **Step 5: Run the endpoint tests**

Run: `cd backend && uv run python -m pytest tests/test_secrets_endpoint.py -v`
Expected: 5 passed.

- [ ] **Step 6: Full backend suite**

Run: `cd backend && uv run python -m pytest -q`
Expected: all tests green (14 Phase 0 + ~15 new = ~29).

- [ ] **Step 7: Commit**

```bash
git add backend/src/agflow/api/admin/secrets.py backend/src/agflow/main.py backend/tests/test_secrets_endpoint.py
git commit -m "feat(m0): admin secrets router — CRUD + reveal + test + resolve-status"
```

---

### Task 7: Frontend i18n strings + secrets API client

**Files:**
- Modify: `frontend/src/i18n/fr.json`
- Modify: `frontend/src/i18n/en.json`
- Create: `frontend/src/lib/secretsApi.ts`

- [ ] **Step 1: Add i18n keys (fr)**

Edit `frontend/src/i18n/fr.json`, add a new `secrets` section at the end (before the last `}`):

```json
  "secrets": {
    "page_title": "Secrets & variables d'environnement",
    "page_subtitle": "Clés API, tokens d'intégration, variables chiffrées en base",
    "add_button": "+ Ajouter un secret",
    "col_name": "Nom de variable",
    "col_value": "Valeur",
    "col_scope": "Scope",
    "col_used_by": "Utilisé par",
    "col_actions": "Actions",
    "scope_global": "Global",
    "scope_agent": "Agent",
    "value_masked": "••••••••",
    "reveal": "Révéler",
    "hide": "Masquer",
    "test": "Tester",
    "edit": "Éditer",
    "delete": "Supprimer",
    "none_used_by": "aucun",
    "form_title_new": "Nouveau secret",
    "form_title_edit": "Modifier le secret",
    "form_name_placeholder": "Ex: ANTHROPIC_API_KEY",
    "form_value_placeholder": "Valeur du secret",
    "form_save": "Enregistrer",
    "form_cancel": "Annuler",
    "confirm_delete": "Supprimer {{name}} ?",
    "test_ok": "Clé valide",
    "test_ko": "Clé invalide",
    "test_unsupported": "Test non disponible pour ce type de variable",
    "error_duplicate": "Ce nom de variable existe déjà",
    "error_generic": "Une erreur est survenue"
  }
```

Make sure to add a comma after the previous section (`status`).

- [ ] **Step 2: Add i18n keys (en)**

Edit `frontend/src/i18n/en.json` identically with English values:

```json
  "secrets": {
    "page_title": "Secrets & environment variables",
    "page_subtitle": "API keys, integration tokens, encrypted at rest",
    "add_button": "+ Add secret",
    "col_name": "Variable name",
    "col_value": "Value",
    "col_scope": "Scope",
    "col_used_by": "Used by",
    "col_actions": "Actions",
    "scope_global": "Global",
    "scope_agent": "Agent",
    "value_masked": "••••••••",
    "reveal": "Reveal",
    "hide": "Hide",
    "test": "Test",
    "edit": "Edit",
    "delete": "Delete",
    "none_used_by": "none",
    "form_title_new": "New secret",
    "form_title_edit": "Edit secret",
    "form_name_placeholder": "E.g. ANTHROPIC_API_KEY",
    "form_value_placeholder": "Secret value",
    "form_save": "Save",
    "form_cancel": "Cancel",
    "confirm_delete": "Delete {{name}}?",
    "test_ok": "Key is valid",
    "test_ko": "Key is invalid",
    "test_unsupported": "Test not available for this variable type",
    "error_duplicate": "This variable name already exists",
    "error_generic": "An error occurred"
  }
```

- [ ] **Step 3: Create the typed API client**

Create `frontend/src/lib/secretsApi.ts`:

```ts
import { api } from "./api";

export type Scope = "global" | "agent";

export interface SecretSummary {
  id: string;
  var_name: string;
  scope: Scope;
  created_at: string;
  updated_at: string;
  used_by: string[];
}

export interface SecretReveal {
  id: string;
  var_name: string;
  value: string;
}

export interface SecretTestResult {
  supported: boolean;
  ok: boolean;
  detail: string;
}

export interface SecretCreate {
  var_name: string;
  value: string;
  scope?: Scope;
}

export interface SecretUpdate {
  value?: string;
  scope?: Scope;
}

export const secretsApi = {
  async list(): Promise<SecretSummary[]> {
    const res = await api.get<SecretSummary[]>("/admin/secrets");
    return res.data;
  },
  async create(payload: SecretCreate): Promise<SecretSummary> {
    const res = await api.post<SecretSummary>("/admin/secrets", payload);
    return res.data;
  },
  async update(id: string, payload: SecretUpdate): Promise<SecretSummary> {
    const res = await api.put<SecretSummary>(`/admin/secrets/${id}`, payload);
    return res.data;
  },
  async remove(id: string): Promise<void> {
    await api.delete(`/admin/secrets/${id}`);
  },
  async reveal(id: string): Promise<SecretReveal> {
    const res = await api.get<SecretReveal>(`/admin/secrets/${id}/reveal`);
    return res.data;
  },
  async test(id: string): Promise<SecretTestResult> {
    const res = await api.post<SecretTestResult>(`/admin/secrets/${id}/test`);
    return res.data;
  },
};
```

- [ ] **Step 4: Verify TS compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/i18n/fr.json frontend/src/i18n/en.json frontend/src/lib/secretsApi.ts
git commit -m "feat(m0): frontend i18n keys + secretsApi client"
```

---

### Task 8: `useSecrets` React Query hook (TDD)

**Files:**
- Create: `frontend/src/hooks/useSecrets.ts`
- Create: `frontend/tests/hooks/useSecrets.test.tsx`

- [ ] **Step 1: Write failing tests**

Create `frontend/tests/hooks/useSecrets.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useSecrets } from "@/hooks/useSecrets";
import { secretsApi } from "@/lib/secretsApi";
import type { ReactNode } from "react";

vi.mock("@/lib/secretsApi", () => ({
  secretsApi: {
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    reveal: vi.fn(),
    test: vi.fn(),
  },
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useSecrets", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("loads secrets via secretsApi.list", async () => {
    vi.mocked(secretsApi.list).mockResolvedValueOnce([
      {
        id: "1",
        var_name: "ANTHROPIC_API_KEY",
        scope: "global",
        created_at: "2026-04-10",
        updated_at: "2026-04-10",
        used_by: [],
      },
    ]);

    const { result } = renderHook(() => useSecrets(), { wrapper });

    await waitFor(() => {
      expect(result.current.secrets).toHaveLength(1);
    });
    expect(result.current.secrets?.[0]?.var_name).toBe("ANTHROPIC_API_KEY");
  });

  it("creates a secret and refetches the list", async () => {
    vi.mocked(secretsApi.list).mockResolvedValue([]);
    vi.mocked(secretsApi.create).mockResolvedValueOnce({
      id: "2",
      var_name: "OPENAI_API_KEY",
      scope: "global",
      created_at: "2026-04-10",
      updated_at: "2026-04-10",
      used_by: [],
    });

    const { result } = renderHook(() => useSecrets(), { wrapper });

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await result.current.createMutation.mutateAsync({
      var_name: "OPENAI_API_KEY",
      value: "sk-openai",
    });

    expect(secretsApi.create).toHaveBeenCalledWith({
      var_name: "OPENAI_API_KEY",
      value: "sk-openai",
    });
  });
});
```

- [ ] **Step 2: Run — expect failure**

Run: `cd frontend && npm test -- tests/hooks/useSecrets.test.tsx`
Expected: `Cannot find module '@/hooks/useSecrets'`.

- [ ] **Step 3: Implement the hook**

Create `frontend/src/hooks/useSecrets.ts`:

```ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  secretsApi,
  type SecretCreate,
  type SecretSummary,
  type SecretUpdate,
} from "@/lib/secretsApi";

const SECRETS_KEY = ["secrets"] as const;

export function useSecrets() {
  const qc = useQueryClient();

  const listQuery = useQuery<SecretSummary[]>({
    queryKey: SECRETS_KEY,
    queryFn: () => secretsApi.list(),
  });

  const createMutation = useMutation({
    mutationFn: (payload: SecretCreate) => secretsApi.create(payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: SECRETS_KEY }),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: SecretUpdate }) =>
      secretsApi.update(id, payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: SECRETS_KEY }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => secretsApi.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: SECRETS_KEY }),
  });

  return {
    secrets: listQuery.data,
    isLoading: listQuery.isLoading,
    error: listQuery.error,
    createMutation,
    updateMutation,
    deleteMutation,
  };
}
```

- [ ] **Step 4: Run tests**

Run: `cd frontend && npm test -- tests/hooks/useSecrets.test.tsx`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/hooks/useSecrets.ts frontend/tests/hooks/useSecrets.test.tsx
git commit -m "feat(m0): useSecrets React Query hook with tests"
```

---

### Task 9: `RevealButton` with auto-hide + `TestKeyButton` (TDD)

**Files:**
- Create: `frontend/src/components/RevealButton.tsx`
- Create: `frontend/src/components/TestKeyButton.tsx`
- Create: `frontend/tests/components/RevealButton.test.tsx`

- [ ] **Step 1: Write failing test for RevealButton**

Create `frontend/tests/components/RevealButton.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RevealButton } from "@/components/RevealButton";
import { secretsApi } from "@/lib/secretsApi";
import "@/lib/i18n";

vi.mock("@/lib/secretsApi", () => ({
  secretsApi: {
    reveal: vi.fn(),
  },
}));

describe("RevealButton", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  it("shows masked value by default", () => {
    render(<RevealButton secretId="abc" />);
    expect(screen.getByText("••••••••")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Révéler/ })).toBeInTheDocument();
  });

  it("reveals the value after clicking", async () => {
    vi.mocked(secretsApi.reveal).mockResolvedValueOnce({
      id: "abc",
      var_name: "TEST",
      value: "my-secret-value",
    });

    render(<RevealButton secretId="abc" />);
    await userEvent.click(screen.getByRole("button", { name: /Révéler/ }));

    expect(await screen.findByText("my-secret-value")).toBeInTheDocument();
    expect(secretsApi.reveal).toHaveBeenCalledWith("abc");
  });

  it("re-masks after clicking Hide", async () => {
    vi.mocked(secretsApi.reveal).mockResolvedValueOnce({
      id: "abc",
      var_name: "TEST",
      value: "my-secret-value",
    });

    render(<RevealButton secretId="abc" />);
    await userEvent.click(screen.getByRole("button", { name: /Révéler/ }));
    await screen.findByText("my-secret-value");

    await userEvent.click(screen.getByRole("button", { name: /Masquer/ }));
    expect(screen.getByText("••••••••")).toBeInTheDocument();
    expect(screen.queryByText("my-secret-value")).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run — expect failure**

Run: `cd frontend && npm test -- tests/components/RevealButton.test.tsx`
Expected: module not found.

- [ ] **Step 3: Implement `RevealButton`**

Create `frontend/src/components/RevealButton.tsx`:

```tsx
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { secretsApi } from "@/lib/secretsApi";

interface Props {
  secretId: string;
  autoHideMs?: number;
}

export function RevealButton({ secretId, autoHideMs = 10000 }: Props) {
  const { t } = useTranslation();
  const [value, setValue] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (value === null) return;
    const timer = setTimeout(() => setValue(null), autoHideMs);
    return () => clearTimeout(timer);
  }, [value, autoHideMs]);

  async function handleReveal() {
    setLoading(true);
    try {
      const res = await secretsApi.reveal(secretId);
      setValue(res.value);
    } finally {
      setLoading(false);
    }
  }

  function handleHide() {
    setValue(null);
  }

  return (
    <span style={{ display: "inline-flex", gap: "0.5rem", alignItems: "center" }}>
      <code>{value ?? t("secrets.value_masked")}</code>
      {value === null ? (
        <button type="button" onClick={handleReveal} disabled={loading}>
          {t("secrets.reveal")}
        </button>
      ) : (
        <button type="button" onClick={handleHide}>
          {t("secrets.hide")}
        </button>
      )}
    </span>
  );
}
```

- [ ] **Step 4: Run tests**

Run: `cd frontend && npm test -- tests/components/RevealButton.test.tsx`
Expected: 3 passed.

- [ ] **Step 5: Implement `TestKeyButton` (no TDD — simple wrapper)**

Create `frontend/src/components/TestKeyButton.tsx`:

```tsx
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { secretsApi, type SecretTestResult } from "@/lib/secretsApi";

interface Props {
  secretId: string;
}

export function TestKeyButton({ secretId }: Props) {
  const { t } = useTranslation();
  const [result, setResult] = useState<SecretTestResult | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleTest() {
    setLoading(true);
    try {
      const res = await secretsApi.test(secretId);
      setResult(res);
    } finally {
      setLoading(false);
    }
  }

  return (
    <span>
      <button type="button" onClick={handleTest} disabled={loading}>
        {t("secrets.test")}
      </button>
      {result && (
        <span style={{ marginLeft: "0.5rem" }}>
          {!result.supported
            ? `⚠️ ${t("secrets.test_unsupported")}`
            : result.ok
              ? `✅ ${t("secrets.test_ok")}`
              : `❌ ${t("secrets.test_ko")} — ${result.detail}`}
        </span>
      )}
    </span>
  );
}
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/RevealButton.tsx frontend/src/components/TestKeyButton.tsx frontend/tests/components/RevealButton.test.tsx
git commit -m "feat(m0): RevealButton + TestKeyButton components"
```

---

### Task 10: `SecretForm` modal (create / edit) (TDD)

**Files:**
- Create: `frontend/src/components/SecretForm.tsx`
- Create: `frontend/tests/components/SecretForm.test.tsx`

- [ ] **Step 1: Write failing test**

Create `frontend/tests/components/SecretForm.test.tsx`:

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SecretForm } from "@/components/SecretForm";
import "@/lib/i18n";

describe("SecretForm", () => {
  it("calls onSubmit with typed values when creating", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const onCancel = vi.fn();

    render(<SecretForm mode="create" onSubmit={onSubmit} onCancel={onCancel} />);

    await userEvent.type(
      screen.getByPlaceholderText(/ANTHROPIC_API_KEY/),
      "openai_api_key",
    );
    await userEvent.type(
      screen.getByPlaceholderText(/Valeur du secret/),
      "sk-openai",
    );
    await userEvent.click(screen.getByRole("button", { name: /Enregistrer/ }));

    expect(onSubmit).toHaveBeenCalledWith({
      var_name: "openai_api_key",
      value: "sk-openai",
      scope: "global",
    });
  });

  it("calls onCancel when Cancel is clicked", async () => {
    const onSubmit = vi.fn();
    const onCancel = vi.fn();

    render(<SecretForm mode="create" onSubmit={onSubmit} onCancel={onCancel} />);

    await userEvent.click(screen.getByRole("button", { name: /Annuler/ }));
    expect(onCancel).toHaveBeenCalled();
  });

  it("pre-fills name in edit mode and only sends value", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const onCancel = vi.fn();

    render(
      <SecretForm
        mode="edit"
        initialName="ANTHROPIC_API_KEY"
        onSubmit={onSubmit}
        onCancel={onCancel}
      />,
    );

    expect(screen.getByDisplayValue("ANTHROPIC_API_KEY")).toBeDisabled();

    await userEvent.type(
      screen.getByPlaceholderText(/Valeur du secret/),
      "new-value",
    );
    await userEvent.click(screen.getByRole("button", { name: /Enregistrer/ }));

    expect(onSubmit).toHaveBeenCalledWith({
      var_name: "ANTHROPIC_API_KEY",
      value: "new-value",
      scope: "global",
    });
  });
});
```

- [ ] **Step 2: Run — expect failure**

Run: `cd frontend && npm test -- tests/components/SecretForm.test.tsx`
Expected: module not found.

- [ ] **Step 3: Implement `SecretForm`**

Create `frontend/src/components/SecretForm.tsx`:

```tsx
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import type { SecretCreate, Scope } from "@/lib/secretsApi";

interface Props {
  mode: "create" | "edit";
  initialName?: string;
  initialScope?: Scope;
  onSubmit: (payload: SecretCreate) => Promise<void> | void;
  onCancel: () => void;
}

export function SecretForm({
  mode,
  initialName = "",
  initialScope = "global",
  onSubmit,
  onCancel,
}: Props) {
  const { t } = useTranslation();
  const [name, setName] = useState(initialName);
  const [value, setValue] = useState("");
  const [scope] = useState<Scope>(initialScope);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      await onSubmit({ var_name: name, value, scope });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      style={{
        border: "1px solid #ccc",
        padding: "1rem",
        borderRadius: "4px",
        maxWidth: 480,
      }}
    >
      <h2>
        {mode === "create"
          ? t("secrets.form_title_new")
          : t("secrets.form_title_edit")}
      </h2>
      <div>
        <label>
          {t("secrets.col_name")}
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t("secrets.form_name_placeholder")}
            disabled={mode === "edit"}
            required
          />
        </label>
      </div>
      <div>
        <label>
          {t("secrets.col_value")}
          <input
            type="password"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder={t("secrets.form_value_placeholder")}
            required
          />
        </label>
      </div>
      <div style={{ display: "flex", gap: "0.5rem", marginTop: "1rem" }}>
        <button type="submit" disabled={submitting}>
          {t("secrets.form_save")}
        </button>
        <button type="button" onClick={onCancel} disabled={submitting}>
          {t("secrets.form_cancel")}
        </button>
      </div>
    </form>
  );
}
```

- [ ] **Step 4: Run tests**

Run: `cd frontend && npm test -- tests/components/SecretForm.test.tsx`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/SecretForm.tsx frontend/tests/components/SecretForm.test.tsx
git commit -m "feat(m0): SecretForm modal with tests"
```

---

### Task 11: `SecretsPage` — table + integration

**Files:**
- Create: `frontend/src/pages/SecretsPage.tsx`
- Create: `frontend/tests/pages/SecretsPage.test.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/pages/HomePage.tsx`

- [ ] **Step 1: Write failing test**

Create `frontend/tests/pages/SecretsPage.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SecretsPage } from "@/pages/SecretsPage";
import { secretsApi } from "@/lib/secretsApi";
import "@/lib/i18n";

vi.mock("@/lib/secretsApi", () => ({
  secretsApi: {
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    reveal: vi.fn(),
    test: vi.fn(),
  },
}));

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <SecretsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("SecretsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders the list of secrets", async () => {
    vi.mocked(secretsApi.list).mockResolvedValueOnce([
      {
        id: "1",
        var_name: "ANTHROPIC_API_KEY",
        scope: "global",
        created_at: "2026-04-10T12:00:00Z",
        updated_at: "2026-04-10T12:00:00Z",
        used_by: [],
      },
    ]);

    renderPage();

    expect(await screen.findByText("ANTHROPIC_API_KEY")).toBeInTheDocument();
  });

  it("opens the form when Add is clicked", async () => {
    vi.mocked(secretsApi.list).mockResolvedValueOnce([]);

    renderPage();

    await waitFor(() =>
      expect(screen.queryByText(/Chargement/)).not.toBeInTheDocument(),
    );

    await userEvent.click(screen.getByRole("button", { name: /Ajouter un secret/ }));
    expect(screen.getByText(/Nouveau secret/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run — expect failure**

Run: `cd frontend && npm test -- tests/pages/SecretsPage.test.tsx`
Expected: module not found.

- [ ] **Step 3: Implement `SecretsPage`**

Create `frontend/src/pages/SecretsPage.tsx`:

```tsx
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useSecrets } from "@/hooks/useSecrets";
import { SecretForm } from "@/components/SecretForm";
import { RevealButton } from "@/components/RevealButton";
import { TestKeyButton } from "@/components/TestKeyButton";
import type { SecretCreate, SecretSummary } from "@/lib/secretsApi";

export function SecretsPage() {
  const { t } = useTranslation();
  const { secrets, isLoading, createMutation, deleteMutation } = useSecrets();
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleCreate(payload: SecretCreate) {
    setError(null);
    try {
      await createMutation.mutateAsync(payload);
      setShowForm(false);
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } }).response?.status;
      setError(
        status === 409 ? t("secrets.error_duplicate") : t("secrets.error_generic"),
      );
    }
  }

  async function handleDelete(secret: SecretSummary) {
    const confirmed = window.confirm(
      t("secrets.confirm_delete", { name: secret.var_name }),
    );
    if (!confirmed) return;
    await deleteMutation.mutateAsync(secret.id);
  }

  return (
    <div style={{ padding: "2rem", maxWidth: 1100 }}>
      <h1>{t("secrets.page_title")}</h1>
      <p>{t("secrets.page_subtitle")}</p>

      <button
        type="button"
        onClick={() => setShowForm(true)}
        disabled={showForm}
        style={{ marginBottom: "1rem" }}
      >
        {t("secrets.add_button")}
      </button>

      {showForm && (
        <div style={{ marginBottom: "1.5rem" }}>
          <SecretForm
            mode="create"
            onSubmit={handleCreate}
            onCancel={() => {
              setShowForm(false);
              setError(null);
            }}
          />
          {error && (
            <p role="alert" style={{ color: "red" }}>
              {error}
            </p>
          )}
        </div>
      )}

      {isLoading ? (
        <p>Chargement…</p>
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr style={{ borderBottom: "1px solid #ccc", textAlign: "left" }}>
              <th>{t("secrets.col_name")}</th>
              <th>{t("secrets.col_value")}</th>
              <th>{t("secrets.col_scope")}</th>
              <th>{t("secrets.col_used_by")}</th>
              <th>{t("secrets.col_actions")}</th>
            </tr>
          </thead>
          <tbody>
            {secrets?.map((secret) => (
              <tr
                key={secret.id}
                style={{ borderBottom: "1px solid #eee" }}
              >
                <td><code>{secret.var_name}</code></td>
                <td>
                  <RevealButton secretId={secret.id} />
                </td>
                <td>
                  {secret.scope === "global"
                    ? t("secrets.scope_global")
                    : t("secrets.scope_agent")}
                </td>
                <td>
                  {secret.used_by.length === 0
                    ? t("secrets.none_used_by")
                    : secret.used_by.join(", ")}
                </td>
                <td style={{ display: "flex", gap: "0.5rem" }}>
                  <TestKeyButton secretId={secret.id} />
                  <button type="button" onClick={() => handleDelete(secret)}>
                    {t("secrets.delete")}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run tests**

Run: `cd frontend && npm test -- tests/pages/SecretsPage.test.tsx`
Expected: 2 passed.

- [ ] **Step 5: Wire the route in `App.tsx`**

Edit `frontend/src/App.tsx`:

Add import:
```tsx
import { SecretsPage } from "./pages/SecretsPage";
```

Add route inside `<Routes>`:
```tsx
      <Route
        path="/secrets"
        element={
          <ProtectedRoute>
            <SecretsPage />
          </ProtectedRoute>
        }
      />
```

- [ ] **Step 6: Add nav link in `HomePage.tsx`**

Edit `frontend/src/pages/HomePage.tsx`:

Add import `Link`:
```tsx
import { Link, useNavigate } from "react-router-dom";
```

Add link before the logout button:
```tsx
      <nav style={{ marginBottom: "1rem" }}>
        <Link to="/secrets">{t("secrets.page_title")}</Link>
      </nav>
```

- [ ] **Step 7: Full frontend suite + TS strict**

Run: `cd frontend && npm test && npx tsc --noEmit`
Expected: all tests green, no TS errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/pages/SecretsPage.tsx frontend/src/App.tsx frontend/src/pages/HomePage.tsx frontend/tests/pages/SecretsPage.test.tsx
git commit -m "feat(m0): SecretsPage wired into router with tests"
```

---

### Task 12: `.env.example` update + deploy on LXC 201 + manual smoke test

**Files:**
- Modify: `.env.example`
- Modify: `.env` (local, not committed)

- [ ] **Step 1: Document the new env var in `.env.example`**

Edit `.env.example`, add after `JWT_SECRET` block:

```bash
# ─── Secrets master key (pgcrypto) — Module 0 ───
# This key encrypts all secret values at rest via pgp_sym_encrypt.
# LOSING IT = all stored secrets become unrecoverable. Back it up.
# Generate with:
#   uv run python -c "import secrets; print(secrets.token_urlsafe(48))"
SECRETS_MASTER_KEY=REPLACE_ME_WITH_A_LONG_RANDOM_STRING_AT_LEAST_48_CHARS
```

- [ ] **Step 2: Add the master key to local `.env`**

Run (in repo root):
```bash
NEW_MASTER=$(cd backend && uv run python -c "import secrets; print(secrets.token_urlsafe(48))")
echo "SECRETS_MASTER_KEY=${NEW_MASTER}" >> .env
grep SECRETS_MASTER_KEY .env
```

- [ ] **Step 3: Rebuild + redeploy on LXC 201**

Run: `./scripts/deploy.sh --rebuild`
Expected: all 5 containers up (postgres, redis, backend, frontend, caddy). Backend picks up new `SECRETS_MASTER_KEY`.

- [ ] **Step 4: Apply migration `002_secrets` on prod DB**

Run:
```bash
ssh pve "pct exec 201 -- docker exec agflow-backend python -m agflow.db.migrations"
```
Expected: log shows `applied=['002_secrets']` (or empty if already applied).

- [ ] **Step 5: Manual smoke test from curl**

```bash
# Login
TOKEN=$(curl -s -X POST http://192.168.10.82/api/admin/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@agflow.example.com","password":"agflow-admin-2026"}' \
  | python -c "import sys, json; print(json.load(sys.stdin)['access_token'])")
echo "Token: ${TOKEN:0:30}..."

# Create a secret
curl -s -X POST http://192.168.10.82/api/admin/secrets \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"var_name":"smoke_test_key","value":"hello-world"}'

# List
curl -s -H "Authorization: Bearer $TOKEN" http://192.168.10.82/api/admin/secrets

# Reveal (note the ID from the list)
SECRET_ID=$(curl -s -H "Authorization: Bearer $TOKEN" http://192.168.10.82/api/admin/secrets \
  | python -c "import sys, json; print([s['id'] for s in json.load(sys.stdin) if s['var_name']=='SMOKE_TEST_KEY'][0])")
curl -s -H "Authorization: Bearer $TOKEN" http://192.168.10.82/api/admin/secrets/$SECRET_ID/reveal

# Delete
curl -s -X DELETE -H "Authorization: Bearer $TOKEN" http://192.168.10.82/api/admin/secrets/$SECRET_ID -w "%{http_code}\n"
```

Expected:
- Create returns 201 with `{"var_name":"SMOKE_TEST_KEY", …}`
- List includes the secret
- Reveal returns `{"value":"hello-world"}`
- Delete returns 204

- [ ] **Step 6: Verify value is encrypted in DB**

```bash
ssh pve "pct exec 201 -- docker exec agflow-postgres psql -U agflow -d agflow -c \"SELECT var_name, length(value_encrypted) FROM secrets LIMIT 5\""
```
Expected: rows with `value_encrypted` length > 30 (encrypted blob, not 11 like "hello-world").

- [ ] **Step 7: Browser test**

Open http://192.168.10.82/, login with admin credentials, click the "Secrets & variables d'environnement" link on the home page. You should see:
- An empty table (or the test secret if not yet deleted)
- "+ Ajouter un secret" button working, opens the form
- Creating a secret adds it to the table
- Clicking "Révéler" shows the value for up to 10 seconds then masks again
- Clicking "Tester" on an ANTHROPIC_API_KEY shows real success/failure based on the key
- Clicking "Supprimer" asks for confirmation and removes the row

- [ ] **Step 8: Final commit + push**

```bash
git add .env.example
git commit -m "docs(m0): document SECRETS_MASTER_KEY in .env.example"
git push origin main
```

---

## Verification end-to-end

After all tasks pass, these should ALL work:

```bash
# Backend tests
cd backend && uv run python -m pytest -v
# → ~29 tests passed (14 Phase 0 + ~15 new)

# Backend lint
cd backend && uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/
# → clean

# Frontend tests
cd frontend && npm test
# → ~18 tests passed (9 Phase 0 + ~9 new)

# Frontend TS strict
cd frontend && npx tsc --noEmit
# → no errors

# Prod smoke (LXC 201)
curl http://192.168.10.82/health
# → {"status":"ok"}

# Create + reveal + delete secret via HTTP
./scripts/smoke-m0.sh  # optional helper, or run the steps in Task 12 Step 5 manually
```

**Browser check:** login → navigate to /secrets → add a secret → reveal it → delete it. All labels in French (or English if switched).

---

## Self-Review Checklist

**1. Spec coverage (Module 0 requirements from specs/home.md):**
- ✅ Types de secrets (API keys, registry keys, integration tokens, app secrets) — freeform var_name
- ✅ Stockage chiffré (pgcrypto) — Task 2, 4
- ✅ Valeurs jamais affichées en clair par défaut — list endpoint does not return `value`, RevealButton explicit
- ✅ Révéler temporairement — RevealButton 10s auto-hide, Task 9
- ✅ Référencement par alias — `var_name` column + UPPER_SNAKE_CASE validator
- ✅ Construction du .env (resolve_env) — Task 4, used by future M4/M5
- ✅ Scoping global/agent — column exists, global works; agent scope UI is out-of-scope for Phase 1 (documented)
- ✅ UI Tableau avec colonnes requises — Task 11
- ✅ Bouton Tester pour LLM keys — TestKeyButton + llm_key_tester.py (Anthropic + OpenAI, others return unsupported)
- ✅ Indicateurs 🔴🟠🟢 — resolve-status endpoint for future module integration, StatusIndicator component already exists from Phase 0
- ⚠ **Used by** column — returns empty list in Phase 1 (no M1/M3/M4 yet). Placeholder only.

**2. Placeholder scan:** Every task has actual code, exact file paths, and concrete verification commands. Placeholder for `used_by` is explicit and documented.

**3. Type consistency:**
- Backend `SecretSummary` fields (id, var_name, scope, created_at, updated_at, used_by) match frontend `SecretSummary` interface.
- Endpoint path `/api/admin/secrets` consistent across router, tests, and frontend API client.
- `createMutation.mutateAsync` signature matches `secretsApi.create(payload)` signature (`{var_name, value, scope?}`).

---

## Execution Handoff

Ready to execute inline with `superpowers:executing-plans` (same approach as Phase 0) or subagent-driven. Inline is recommended here too since Phase 1 builds directly on the Phase 0 skeleton with no blocking env discoveries expected.
