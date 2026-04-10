# agflow.docker Phase 2 — Module 2 (Rôles) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Module 2 (Rôles) — CRUD roles with personality configuration, arborescent documents (ROLES / MISSIONS / COMPETENCES sub-sections) with protected flag, auto-generation of 2nd-person (agent) + 3rd-person (orchestrator) prompt variants via Anthropic. End state: an admin can create a role "Analyst", add documents in each section, click "Regenerate prompts", and see two coherent markdown variants stored and displayed.

**Architecture:** Backend exposes `/api/admin/roles/*` routes. Roles live in the `roles` table (slug PK). Documents live in `role_documents` (FK `role_id`, section + name). Prompt generation uses the `ANTHROPIC_API_KEY` resolved via Module 0's `secrets_service.resolve_env()` (first real integration with M0). Frontend is a 3-column admin page: role selector (left), sidebar tree (middle), tab-based editor (right: General / Identity / Prompt). Protected documents are enforced backend-side (403) and signaled UI-side (🔒 icon, disabled editor).

**Tech Stack:** Backend — anthropic SDK (already in deps), asyncpg, FastAPI, structlog, pytest. Frontend — React 18 + TS strict, @tanstack/react-query, i18next, react-router-dom (existing).

---

## Context

Phase 0 bootstrapped the stack. Phase 1 delivered Module 0 (Secrets) with `resolve_env()` — this phase is the first real consumer of that API. After M2, the platform will be able to:
- Store a personality (role) with all its composable documents (facettes, missions, compétences)
- Compile a "2nd person" system prompt for injection into an agent container
- Compile a "3rd person" description for the orchestrator's routing logic

Module 2 does not yet reference Dockerfiles or agents — those come in M1 / M4. In Phase 2, roles are standalone entities.

**What is NOT in this phase:**
- **Chat co-building UI** — the spec mentions "Discutez avec le LLM pour construire le profil". Phase 2 ships a placeholder only (empty tab), actual conversational editor in a later phase.
- **Import / Export** — the "Importer" button is a placeholder only.
- **Directory / group nesting in sidebar** — schema supports `parent_path` but Phase 2 UI only shows a flat list per section.
- **Manual override of generated prompts** — Phase 2 regenerates on demand; a future iteration will allow hand-editing and locking.
- **Service type filtering** — the 7-checkbox `service_types` is stored but not used to filter anything yet (documented intent for future modules to consume).

---

## File Structure

### Backend — files created
- `backend/migrations/003_roles.sql`
- `backend/migrations/004_role_documents.sql`
- `backend/src/agflow/schemas/roles.py`
- `backend/src/agflow/services/roles_service.py`
- `backend/src/agflow/services/role_documents_service.py`
- `backend/src/agflow/services/prompt_generator.py`
- `backend/src/agflow/api/admin/roles.py`
- `backend/tests/test_roles_service.py`
- `backend/tests/test_role_documents_service.py`
- `backend/tests/test_prompt_generator.py`
- `backend/tests/test_roles_endpoint.py`

### Backend — files modified
- `backend/src/agflow/main.py` (register router)

### Frontend — files created
- `frontend/src/lib/rolesApi.ts`
- `frontend/src/hooks/useRoles.ts`
- `frontend/src/hooks/useRoleDocuments.ts`
- `frontend/src/components/MarkdownEditor.tsx`
- `frontend/src/components/RoleSidebar.tsx`
- `frontend/src/components/RoleGeneralTab.tsx`
- `frontend/src/components/RoleIdentityTab.tsx`
- `frontend/src/components/RolePromptTab.tsx`
- `frontend/src/pages/RolesPage.tsx`
- `frontend/tests/hooks/useRoles.test.tsx`
- `frontend/tests/components/MarkdownEditor.test.tsx`
- `frontend/tests/components/RoleSidebar.test.tsx`
- `frontend/tests/pages/RolesPage.test.tsx`

### Frontend — files modified
- `frontend/src/App.tsx` (add `/roles` route)
- `frontend/src/pages/HomePage.tsx` (nav link)
- `frontend/src/i18n/fr.json` + `en.json`

---

## Data model

### `roles` table (migration `003_roles.sql`)

```sql
CREATE TABLE IF NOT EXISTS roles (
    id              TEXT PRIMARY KEY,
    display_name    TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    llm_type        TEXT NOT NULL DEFAULT 'single'
                    CHECK (llm_type IN ('single', 'multi')),
    temperature     NUMERIC(3,2) NOT NULL DEFAULT 0.3
                    CHECK (temperature >= 0 AND temperature <= 2),
    max_tokens      INTEGER NOT NULL DEFAULT 4096
                    CHECK (max_tokens > 0),
    service_types   TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
    identity_md     TEXT NOT NULL DEFAULT '',
    prompt_agent_md TEXT NOT NULL DEFAULT '',
    prompt_orchestrator_md TEXT NOT NULL DEFAULT '',
    runtime_config  JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_roles_display_name ON roles(display_name);
```

The `id` is a slug (user-provided, ex: `requirements_analyst`) and also the PK — simpler than UUID since slugs are naturally unique and stable.

### `role_documents` table (migration `004_role_documents.sql`)

```sql
CREATE TABLE IF NOT EXISTS role_documents (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    role_id     TEXT NOT NULL REFERENCES roles(id) ON DELETE CASCADE,
    section     TEXT NOT NULL
                CHECK (section IN ('roles', 'missions', 'competences')),
    parent_path TEXT NOT NULL DEFAULT '',
    name        TEXT NOT NULL,
    content_md  TEXT NOT NULL DEFAULT '',
    protected   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (role_id, section, parent_path, name)
);

CREATE INDEX IF NOT EXISTS idx_role_documents_role_section
    ON role_documents(role_id, section);
```

`parent_path` is for future grouping (empty string = top level of the section). Phase 2 always writes `''` and never displays nested directories.

### API shape

| Endpoint | Method | Body | Returns |
|---|---|---|---|
| `/api/admin/roles` | GET | — | `list[RoleSummary]` |
| `/api/admin/roles` | POST | `RoleCreate` | `RoleSummary` (201) |
| `/api/admin/roles/{id}` | GET | — | `RoleDetail` (with documents grouped by section) |
| `/api/admin/roles/{id}` | PUT | `RoleUpdate` | `RoleSummary` |
| `/api/admin/roles/{id}` | DELETE | — | 204 |
| `/api/admin/roles/{id}/documents` | GET | — | `list[DocumentSummary]` |
| `/api/admin/roles/{id}/documents` | POST | `DocumentCreate` | `DocumentSummary` (201) |
| `/api/admin/roles/{id}/documents/{doc_id}` | PUT | `DocumentUpdate` | `DocumentSummary` |
| `/api/admin/roles/{id}/documents/{doc_id}` | DELETE | — | 204 |
| `/api/admin/roles/{id}/generate-prompts` | POST | — | `RoleSummary` (with updated prompts) |

All under `Depends(require_admin)`.

---

## Tasks

### Task 1: Migrations 003 + 004 (roles + documents)

**Files:**
- Create: `backend/migrations/003_roles.sql`
- Create: `backend/migrations/004_role_documents.sql`
- Modify: `backend/tests/test_migrations.py` (add test for new migrations)

- [ ] **Step 1: Write `003_roles.sql`**

Create `backend/migrations/003_roles.sql` with the SQL from the "Data model" section above (roles table + index).

- [ ] **Step 2: Write `004_role_documents.sql`**

Create `backend/migrations/004_role_documents.sql` with the SQL from the "Data model" section above (role_documents table + index).

- [ ] **Step 3: Add a test for the new migrations**

Edit `backend/tests/test_migrations.py`, append at the end:

```python
@pytest.mark.asyncio
async def test_migrations_003_and_004_create_roles_tables() -> None:
    await execute("DROP TABLE IF EXISTS role_documents CASCADE")
    await execute("DROP TABLE IF EXISTS roles CASCADE")
    await execute("DROP TABLE IF EXISTS secrets CASCADE")
    await execute("DROP TABLE IF EXISTS schema_migrations CASCADE")

    applied = await run_migrations(_MIGRATIONS_DIR)

    assert "003_roles" in applied
    assert "004_role_documents" in applied

    row = await fetch_one(
        """
        SELECT table_name FROM information_schema.tables
        WHERE table_name IN ('roles', 'role_documents')
        ORDER BY table_name
        """
    )
    assert row is not None

    fk = await fetch_one(
        """
        SELECT confrelid::regclass::text AS ref
        FROM pg_constraint
        WHERE conname LIKE 'role_documents_role_id_fkey%'
        """
    )
    assert fk is not None
    assert "roles" in fk["ref"]
    await close_pool()
```

- [ ] **Step 4: Run the migration tests**

Run: `cd backend && uv run python -m pytest tests/test_migrations.py -v`
Expected: 4 passed (3 previous + 1 new).

- [ ] **Step 5: Commit**

```bash
git add backend/migrations/003_roles.sql backend/migrations/004_role_documents.sql backend/tests/test_migrations.py
git commit -m "feat(m2): migrations 003_roles + 004_role_documents"
```

---

### Task 2: Pydantic schemas for roles & documents

**Files:**
- Create: `backend/src/agflow/schemas/roles.py`

- [ ] **Step 1: Create `schemas/roles.py`**

Create `backend/src/agflow/schemas/roles.py`:

```python
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

LLMType = Literal["single", "multi"]
Section = Literal["roles", "missions", "competences"]

_ALLOWED_SERVICE_TYPES = {
    "documentation",
    "code",
    "design",
    "automation",
    "task_list",
    "specs",
    "contract",
}


class RoleCreate(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=200)
    description: str = ""
    llm_type: LLMType = "single"
    temperature: float = Field(default=0.3, ge=0, le=2)
    max_tokens: int = Field(default=4096, gt=0)
    service_types: list[str] = Field(default_factory=list)
    identity_md: str = ""

    @field_validator("id")
    @classmethod
    def _slug(cls, v: str) -> str:
        v = v.strip().lower()
        if not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError(
                "id must be a slug: lowercase alphanumeric + _ and -"
            )
        return v

    @field_validator("service_types")
    @classmethod
    def _valid_services(cls, v: list[str]) -> list[str]:
        unknown = [s for s in v if s not in _ALLOWED_SERVICE_TYPES]
        if unknown:
            raise ValueError(f"Unknown service types: {unknown}")
        return v


class RoleUpdate(BaseModel):
    display_name: str | None = None
    description: str | None = None
    llm_type: LLMType | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, gt=0)
    service_types: list[str] | None = None
    identity_md: str | None = None
    runtime_config: dict | None = None

    @field_validator("service_types")
    @classmethod
    def _valid_services(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        unknown = [s for s in v if s not in _ALLOWED_SERVICE_TYPES]
        if unknown:
            raise ValueError(f"Unknown service types: {unknown}")
        return v


class RoleSummary(BaseModel):
    id: str
    display_name: str
    description: str
    llm_type: LLMType
    temperature: float
    max_tokens: int
    service_types: list[str]
    identity_md: str
    prompt_agent_md: str
    prompt_orchestrator_md: str
    runtime_config: dict
    created_at: datetime
    updated_at: datetime


class DocumentCreate(BaseModel):
    section: Section
    name: str = Field(min_length=1, max_length=200)
    content_md: str = ""
    protected: bool = False

    @field_validator("name")
    @classmethod
    def _slug(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must be non-empty")
        return v


class DocumentUpdate(BaseModel):
    content_md: str | None = None
    protected: bool | None = None


class DocumentSummary(BaseModel):
    id: UUID
    role_id: str
    section: Section
    parent_path: str
    name: str
    content_md: str
    protected: bool
    created_at: datetime
    updated_at: datetime


class RoleDetail(BaseModel):
    role: RoleSummary
    roles_documents: list[DocumentSummary]
    missions_documents: list[DocumentSummary]
    competences_documents: list[DocumentSummary]
```

- [ ] **Step 2: Smoke test the schemas**

Run:
```bash
cd backend && uv run python -c "
from agflow.schemas.roles import RoleCreate
r = RoleCreate(id='Requirements_Analyst', display_name='Analyst', service_types=['code', 'specs'])
print(r.id, r.service_types)
"
```
Expected: `requirements_analyst ['code', 'specs']` (slug lowered, service_types valid).

- [ ] **Step 3: Commit**

```bash
git add backend/src/agflow/schemas/roles.py
git commit -m "feat(m2): Pydantic schemas for roles + documents"
```

---

### Task 3: `roles_service.py` + CRUD tests (TDD)

**Files:**
- Create: `backend/src/agflow/services/roles_service.py`
- Create: `backend/tests/test_roles_service.py`

- [ ] **Step 1: Write the failing test file**

Create `backend/tests/test_roles_service.py`:

```python
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ["DATABASE_URL"] = "postgresql://agflow:agflow_dev@192.168.10.82:5432/agflow"
os.environ.setdefault("SECRETS_MASTER_KEY", "test-master-key-phrase-32chars-ok")

from agflow.db.migrations import run_migrations  # noqa: E402
from agflow.db.pool import close_pool, execute  # noqa: E402
from agflow.services import roles_service  # noqa: E402

_MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


@pytest.fixture(autouse=True)
async def _clean():
    await execute("DROP TABLE IF EXISTS role_documents CASCADE")
    await execute("DROP TABLE IF EXISTS roles CASCADE")
    await execute("DROP TABLE IF EXISTS secrets CASCADE")
    await execute("DROP TABLE IF EXISTS schema_migrations CASCADE")
    await run_migrations(_MIGRATIONS_DIR)
    yield
    await close_pool()


@pytest.mark.asyncio
async def test_create_and_get_role() -> None:
    summary = await roles_service.create(
        role_id="analyst",
        display_name="Analyst",
        description="Extracts requirements",
        llm_type="single",
        temperature=0.2,
        max_tokens=8000,
        service_types=["specs", "code"],
        identity_md="Tu es un analyste.",
    )

    assert summary.id == "analyst"
    assert summary.display_name == "Analyst"
    assert summary.service_types == ["specs", "code"]
    assert summary.identity_md == "Tu es un analyste."
    assert summary.prompt_agent_md == ""  # not generated yet

    again = await roles_service.get_by_id("analyst")
    assert again.display_name == "Analyst"


@pytest.mark.asyncio
async def test_create_rejects_duplicate_id() -> None:
    await roles_service.create(role_id="dup", display_name="A")
    with pytest.raises(roles_service.DuplicateRoleError):
        await roles_service.create(role_id="dup", display_name="B")


@pytest.mark.asyncio
async def test_list_roles_sorted_by_display_name() -> None:
    await roles_service.create(role_id="b_role", display_name="Beta")
    await roles_service.create(role_id="a_role", display_name="Alpha")

    roles = await roles_service.list_all()
    names = [r.display_name for r in roles]
    assert names == ["Alpha", "Beta"]


@pytest.mark.asyncio
async def test_update_role_partial() -> None:
    await roles_service.create(role_id="upd", display_name="Old", temperature=0.1)

    updated = await roles_service.update(
        "upd", display_name="New", temperature=0.7
    )
    assert updated.display_name == "New"
    assert updated.temperature == 0.7


@pytest.mark.asyncio
async def test_delete_role() -> None:
    await roles_service.create(role_id="to_del", display_name="ToDelete")

    await roles_service.delete("to_del")

    with pytest.raises(roles_service.RoleNotFoundError):
        await roles_service.get_by_id("to_del")


@pytest.mark.asyncio
async def test_get_missing_raises() -> None:
    with pytest.raises(roles_service.RoleNotFoundError):
        await roles_service.get_by_id("does-not-exist")


@pytest.mark.asyncio
async def test_update_prompts() -> None:
    await roles_service.create(role_id="p", display_name="P")

    updated = await roles_service.update_prompts(
        "p",
        prompt_agent_md="Tu es un assistant.",
        prompt_orchestrator_md="Il est un assistant.",
    )
    assert updated.prompt_agent_md == "Tu es un assistant."
    assert updated.prompt_orchestrator_md == "Il est un assistant."
```

- [ ] **Step 2: Run — expect ModuleNotFoundError**

Run: `cd backend && uv run python -m pytest tests/test_roles_service.py -v`
Expected: `ModuleNotFoundError: No module named 'agflow.services.roles_service'`.

- [ ] **Step 3: Implement `roles_service.py`**

Create `backend/src/agflow/services/roles_service.py`:

```python
from __future__ import annotations

from typing import Any

import asyncpg
import structlog

from agflow.db.pool import fetch_all, fetch_one, get_pool
from agflow.schemas.roles import LLMType, RoleSummary

_log = structlog.get_logger(__name__)

_ROLE_COLS = (
    "id, display_name, description, llm_type, temperature, max_tokens, "
    "service_types, identity_md, prompt_agent_md, prompt_orchestrator_md, "
    "runtime_config, created_at, updated_at"
)


class RoleNotFoundError(Exception):
    pass


class DuplicateRoleError(Exception):
    pass


def _row_to_summary(row: dict[str, Any]) -> RoleSummary:
    return RoleSummary(
        id=row["id"],
        display_name=row["display_name"],
        description=row["description"],
        llm_type=row["llm_type"],
        temperature=float(row["temperature"]),
        max_tokens=row["max_tokens"],
        service_types=list(row["service_types"]),
        identity_md=row["identity_md"],
        prompt_agent_md=row["prompt_agent_md"],
        prompt_orchestrator_md=row["prompt_orchestrator_md"],
        runtime_config=row["runtime_config"] or {},
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def create(
    role_id: str,
    display_name: str,
    description: str = "",
    llm_type: LLMType = "single",
    temperature: float = 0.3,
    max_tokens: int = 4096,
    service_types: list[str] | None = None,
    identity_md: str = "",
) -> RoleSummary:
    try:
        row = await fetch_one(
            f"""
            INSERT INTO roles (
                id, display_name, description, llm_type, temperature,
                max_tokens, service_types, identity_md
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING {_ROLE_COLS}
            """,
            role_id,
            display_name,
            description,
            llm_type,
            temperature,
            max_tokens,
            service_types or [],
            identity_md,
        )
    except asyncpg.UniqueViolationError as exc:
        raise DuplicateRoleError(f"Role '{role_id}' already exists") from exc
    assert row is not None
    _log.info("roles.create", role_id=role_id)
    return _row_to_summary(row)


async def list_all() -> list[RoleSummary]:
    rows = await fetch_all(
        f"SELECT {_ROLE_COLS} FROM roles ORDER BY display_name ASC"
    )
    return [_row_to_summary(r) for r in rows]


async def get_by_id(role_id: str) -> RoleSummary:
    row = await fetch_one(
        f"SELECT {_ROLE_COLS} FROM roles WHERE id = $1", role_id
    )
    if row is None:
        raise RoleNotFoundError(f"Role '{role_id}' not found")
    return _row_to_summary(row)


async def update(role_id: str, **fields: Any) -> RoleSummary:
    allowed = {
        "display_name",
        "description",
        "llm_type",
        "temperature",
        "max_tokens",
        "service_types",
        "identity_md",
        "runtime_config",
    }
    sets: list[str] = []
    args: list[Any] = []
    idx = 1
    for key, value in fields.items():
        if value is None or key not in allowed:
            continue
        sets.append(f"{key} = ${idx}")
        args.append(value)
        idx += 1
    if not sets:
        return await get_by_id(role_id)
    sets.append("updated_at = NOW()")
    args.append(role_id)
    query = (
        f"UPDATE roles SET {', '.join(sets)} WHERE id = ${idx} RETURNING {_ROLE_COLS}"
    )
    row = await fetch_one(query, *args)
    if row is None:
        raise RoleNotFoundError(f"Role '{role_id}' not found")
    _log.info("roles.update", role_id=role_id, fields=list(fields.keys()))
    return _row_to_summary(row)


async def update_prompts(
    role_id: str,
    prompt_agent_md: str,
    prompt_orchestrator_md: str,
) -> RoleSummary:
    row = await fetch_one(
        f"""
        UPDATE roles SET
            prompt_agent_md = $2,
            prompt_orchestrator_md = $3,
            updated_at = NOW()
        WHERE id = $1
        RETURNING {_ROLE_COLS}
        """,
        role_id,
        prompt_agent_md,
        prompt_orchestrator_md,
    )
    if row is None:
        raise RoleNotFoundError(f"Role '{role_id}' not found")
    _log.info("roles.update_prompts", role_id=role_id)
    return _row_to_summary(row)


async def delete(role_id: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM roles WHERE id = $1", role_id)
    if result == "DELETE 0":
        raise RoleNotFoundError(f"Role '{role_id}' not found")
    _log.info("roles.delete", role_id=role_id)
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run python -m pytest tests/test_roles_service.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/agflow/services/roles_service.py backend/tests/test_roles_service.py
git commit -m "feat(m2): roles_service CRUD with 7 tests"
```

---

### Task 4: `role_documents_service.py` + tests (TDD)

**Files:**
- Create: `backend/src/agflow/services/role_documents_service.py`
- Create: `backend/tests/test_role_documents_service.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_role_documents_service.py`:

```python
from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest

os.environ["DATABASE_URL"] = "postgresql://agflow:agflow_dev@192.168.10.82:5432/agflow"
os.environ.setdefault("SECRETS_MASTER_KEY", "test-master-key-phrase-32chars-ok")

from agflow.db.migrations import run_migrations  # noqa: E402
from agflow.db.pool import close_pool, execute  # noqa: E402
from agflow.services import role_documents_service as docs  # noqa: E402
from agflow.services import roles_service  # noqa: E402

_MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


@pytest.fixture(autouse=True)
async def _clean():
    await execute("DROP TABLE IF EXISTS role_documents CASCADE")
    await execute("DROP TABLE IF EXISTS roles CASCADE")
    await execute("DROP TABLE IF EXISTS secrets CASCADE")
    await execute("DROP TABLE IF EXISTS schema_migrations CASCADE")
    await run_migrations(_MIGRATIONS_DIR)
    await roles_service.create(role_id="test_role", display_name="Test")
    yield
    await close_pool()


@pytest.mark.asyncio
async def test_create_document() -> None:
    doc = await docs.create(
        role_id="test_role",
        section="roles",
        name="analyse_extraction",
        content_md="# Analyse\nTu analyses...",
    )

    assert doc.role_id == "test_role"
    assert doc.section == "roles"
    assert doc.name == "analyse_extraction"
    assert doc.protected is False


@pytest.mark.asyncio
async def test_create_rejects_duplicate_name() -> None:
    await docs.create(role_id="test_role", section="missions", name="dup")
    with pytest.raises(docs.DuplicateDocumentError):
        await docs.create(role_id="test_role", section="missions", name="dup")


@pytest.mark.asyncio
async def test_list_by_role_grouped_by_section() -> None:
    await docs.create(role_id="test_role", section="roles", name="r1")
    await docs.create(role_id="test_role", section="missions", name="m1")
    await docs.create(role_id="test_role", section="competences", name="c1")

    all_docs = await docs.list_for_role("test_role")
    assert len(all_docs) == 3

    roles = [d for d in all_docs if d.section == "roles"]
    missions = [d for d in all_docs if d.section == "missions"]
    comp = [d for d in all_docs if d.section == "competences"]
    assert len(roles) == 1
    assert len(missions) == 1
    assert len(comp) == 1


@pytest.mark.asyncio
async def test_update_content() -> None:
    doc = await docs.create(role_id="test_role", section="roles", name="u")

    updated = await docs.update(doc.id, content_md="new content")

    assert updated.content_md == "new content"


@pytest.mark.asyncio
async def test_protected_document_cannot_be_updated() -> None:
    doc = await docs.create(
        role_id="test_role",
        section="roles",
        name="locked",
        protected=True,
    )

    with pytest.raises(docs.ProtectedDocumentError):
        await docs.update(doc.id, content_md="should fail")


@pytest.mark.asyncio
async def test_protected_document_cannot_be_deleted() -> None:
    doc = await docs.create(
        role_id="test_role",
        section="roles",
        name="locked_del",
        protected=True,
    )

    with pytest.raises(docs.ProtectedDocumentError):
        await docs.delete(doc.id)


@pytest.mark.asyncio
async def test_delete_unprotected() -> None:
    doc = await docs.create(role_id="test_role", section="roles", name="del")

    await docs.delete(doc.id)

    remaining = await docs.list_for_role("test_role")
    assert all(d.id != doc.id for d in remaining)


@pytest.mark.asyncio
async def test_document_missing_raises() -> None:
    with pytest.raises(docs.DocumentNotFoundError):
        await docs.get_by_id(uuid.uuid4())


@pytest.mark.asyncio
async def test_toggle_protected_flag() -> None:
    doc = await docs.create(role_id="test_role", section="roles", name="flag")

    # First: explicitly toggle protected=True
    updated = await docs.update(doc.id, protected=True)
    assert updated.protected is True

    # Now the doc is protected → content update should fail
    with pytest.raises(docs.ProtectedDocumentError):
        await docs.update(doc.id, content_md="x")

    # But toggling protected back to False MUST work (escape hatch)
    unlocked = await docs.update(doc.id, protected=False)
    assert unlocked.protected is False
```

- [ ] **Step 2: Run — expect failure**

Run: `cd backend && uv run python -m pytest tests/test_role_documents_service.py -v`
Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `role_documents_service.py`**

Create `backend/src/agflow/services/role_documents_service.py`:

```python
from __future__ import annotations

from uuid import UUID

import asyncpg
import structlog

from agflow.db.pool import fetch_all, fetch_one, get_pool
from agflow.schemas.roles import DocumentSummary, Section

_log = structlog.get_logger(__name__)

_DOC_COLS = (
    "id, role_id, section, parent_path, name, content_md, protected, "
    "created_at, updated_at"
)


class DocumentNotFoundError(Exception):
    pass


class DuplicateDocumentError(Exception):
    pass


class ProtectedDocumentError(Exception):
    pass


def _row(row: dict) -> DocumentSummary:
    return DocumentSummary(**row)


async def create(
    role_id: str,
    section: Section,
    name: str,
    parent_path: str = "",
    content_md: str = "",
    protected: bool = False,
) -> DocumentSummary:
    try:
        row = await fetch_one(
            f"""
            INSERT INTO role_documents (
                role_id, section, parent_path, name, content_md, protected
            )
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING {_DOC_COLS}
            """,
            role_id,
            section,
            parent_path,
            name,
            content_md,
            protected,
        )
    except asyncpg.UniqueViolationError as exc:
        raise DuplicateDocumentError(
            f"Document '{name}' already exists in {section} for role '{role_id}'"
        ) from exc
    assert row is not None
    _log.info("role_documents.create", role_id=role_id, section=section, name=name)
    return _row(row)


async def get_by_id(doc_id: UUID) -> DocumentSummary:
    row = await fetch_one(
        f"SELECT {_DOC_COLS} FROM role_documents WHERE id = $1", doc_id
    )
    if row is None:
        raise DocumentNotFoundError(f"Document {doc_id} not found")
    return _row(row)


async def list_for_role(role_id: str) -> list[DocumentSummary]:
    rows = await fetch_all(
        f"""
        SELECT {_DOC_COLS} FROM role_documents
        WHERE role_id = $1
        ORDER BY section ASC, parent_path ASC, name ASC
        """,
        role_id,
    )
    return [_row(r) for r in rows]


async def update(
    doc_id: UUID,
    content_md: str | None = None,
    protected: bool | None = None,
) -> DocumentSummary:
    current = await get_by_id(doc_id)

    # Block content updates if the document is currently protected.
    # Protected flag toggling is always allowed (escape hatch).
    if current.protected and content_md is not None:
        raise ProtectedDocumentError(
            f"Document '{current.name}' is protected; unlock it first"
        )

    sets: list[str] = []
    args: list[object] = []
    idx = 1
    if content_md is not None:
        sets.append(f"content_md = ${idx}")
        args.append(content_md)
        idx += 1
    if protected is not None:
        sets.append(f"protected = ${idx}")
        args.append(protected)
        idx += 1
    if not sets:
        return current
    sets.append("updated_at = NOW()")
    args.append(doc_id)

    row = await fetch_one(
        f"""
        UPDATE role_documents SET {", ".join(sets)}
        WHERE id = ${idx}
        RETURNING {_DOC_COLS}
        """,
        *args,
    )
    assert row is not None
    _log.info("role_documents.update", doc_id=str(doc_id))
    return _row(row)


async def delete(doc_id: UUID) -> None:
    current = await get_by_id(doc_id)
    if current.protected:
        raise ProtectedDocumentError(
            f"Document '{current.name}' is protected; unlock it first"
        )
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM role_documents WHERE id = $1", doc_id)
    _log.info("role_documents.delete", doc_id=str(doc_id))
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run python -m pytest tests/test_role_documents_service.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/agflow/services/role_documents_service.py backend/tests/test_role_documents_service.py
git commit -m "feat(m2): role_documents_service with protected flag enforcement"
```

---

### Task 5: `prompt_generator.py` with Anthropic (TDD, mocked)

**Files:**
- Create: `backend/src/agflow/services/prompt_generator.py`
- Create: `backend/tests/test_prompt_generator.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_prompt_generator.py`:

```python
from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost/test")
os.environ.setdefault("JWT_SECRET", "x")
os.environ.setdefault("ADMIN_EMAIL", "a@b.c")
os.environ.setdefault("ADMIN_PASSWORD_HASH", "x")
os.environ.setdefault("SECRETS_MASTER_KEY", "x")

from agflow.schemas.roles import DocumentSummary, RoleSummary  # noqa: E402
from agflow.services import prompt_generator  # noqa: E402


def _make_role() -> RoleSummary:
    from datetime import datetime

    return RoleSummary(
        id="analyst",
        display_name="Analyst",
        description="",
        llm_type="single",
        temperature=0.2,
        max_tokens=4096,
        service_types=[],
        identity_md="Tu es un analyste rigoureux.",
        prompt_agent_md="",
        prompt_orchestrator_md="",
        runtime_config={},
        created_at=datetime(2026, 4, 10),
        updated_at=datetime(2026, 4, 10),
    )


def _make_doc(section: str, name: str, content: str) -> DocumentSummary:
    from datetime import datetime
    from uuid import uuid4

    return DocumentSummary(
        id=uuid4(),
        role_id="analyst",
        section=section,  # type: ignore[arg-type]
        parent_path="",
        name=name,
        content_md=content,
        protected=False,
        created_at=datetime(2026, 4, 10),
        updated_at=datetime(2026, 4, 10),
    )


def test_assemble_source_markdown_orders_sections() -> None:
    role = _make_role()
    documents = [
        _make_doc("missions", "m1", "Tu transformes sans reformater."),
        _make_doc("roles", "r1", "Tu analyses et extrais."),
        _make_doc("competences", "c1", "Tu maîtrises la déduction logique."),
    ]

    source = prompt_generator.assemble_source_markdown(role, documents)

    assert "# Identité" in source
    assert "Tu es un analyste rigoureux." in source
    # Order must be identity → roles → missions → competences
    identity_idx = source.index("# Identité")
    roles_idx = source.index("## Rôles")
    missions_idx = source.index("## Missions")
    competences_idx = source.index("## Compétences")
    assert identity_idx < roles_idx < missions_idx < competences_idx
    assert "Tu analyses et extrais." in source
    assert "Tu transformes sans reformater." in source
    assert "Tu maîtrises la déduction logique." in source


@pytest.mark.asyncio
async def test_generate_prompts_calls_anthropic_twice() -> None:
    role = _make_role()
    docs = [_make_doc("roles", "r1", "Tu analyses.")]

    call_count = {"n": 0}

    class _FakeMessage:
        def __init__(self, text: str) -> None:
            self.content = [type("Block", (), {"text": text})()]

    async def _fake_create(**kwargs: object) -> _FakeMessage:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _FakeMessage("Tu es un assistant qui analyse.")
        return _FakeMessage("Il est un assistant qui analyse.")

    fake_client = type(
        "FakeClient",
        (),
        {"messages": type("M", (), {"create": staticmethod(_fake_create)})()},
    )()

    with patch(
        "agflow.services.prompt_generator._get_anthropic_client",
        new=AsyncMock(return_value=fake_client),
    ):
        result = await prompt_generator.generate_prompts(role, docs)

    assert result.prompt_agent_md.startswith("Tu es")
    assert result.prompt_orchestrator_md.startswith("Il est")
    assert call_count["n"] == 2


@pytest.mark.asyncio
async def test_generate_prompts_raises_if_no_anthropic_key() -> None:
    from agflow.services import secrets_service

    role = _make_role()
    docs: list[DocumentSummary] = []

    async def _raise_missing(names: list[str]) -> dict[str, str]:
        raise secrets_service.SecretNotFoundError("Missing: ANTHROPIC_API_KEY")

    with patch(
        "agflow.services.prompt_generator.secrets_service.resolve_env",
        new=_raise_missing,
    ):
        with pytest.raises(prompt_generator.MissingAnthropicKeyError):
            await prompt_generator.generate_prompts(role, docs)
```

- [ ] **Step 2: Run — expect ModuleNotFoundError**

Run: `cd backend && uv run python -m pytest tests/test_prompt_generator.py -v`
Expected: module not found.

- [ ] **Step 3: Implement `prompt_generator.py`**

Create `backend/src/agflow/services/prompt_generator.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

import anthropic
import structlog

from agflow.schemas.roles import DocumentSummary, RoleSummary
from agflow.services import secrets_service

_log = structlog.get_logger(__name__)

CLAUDE_MODEL = "claude-sonnet-4-5"


class MissingAnthropicKeyError(Exception):
    pass


@dataclass
class GeneratedPrompts:
    prompt_agent_md: str
    prompt_orchestrator_md: str


def assemble_source_markdown(
    role: RoleSummary, documents: list[DocumentSummary]
) -> str:
    """Concatenate identity + all documents grouped by section into one markdown."""
    parts: list[str] = []
    parts.append("# Identité")
    parts.append("")
    parts.append(role.identity_md or "(identité non renseignée)")
    parts.append("")

    sections = {"roles": "Rôles", "missions": "Missions", "competences": "Compétences"}
    for section, title in sections.items():
        docs = [d for d in documents if d.section == section]
        if not docs:
            continue
        parts.append(f"## {title}")
        parts.append("")
        for doc in sorted(docs, key=lambda d: d.name):
            parts.append(f"### {doc.name}")
            parts.append("")
            parts.append(doc.content_md)
            parts.append("")

    return "\n".join(parts)


_AGENT_PROMPT_TEMPLATE = """\
Tu es un assembleur de prompts. Voici la description d'un agent IA \
sous forme d'identité + facettes. Compose un prompt système cohérent à \
la deuxième personne du singulier ("Tu es...", "Tu analyses...") qui \
fusionne tout ce contenu en un texte clair, direct et actionnable. \
N'ajoute pas de méta-commentaire, de titre, ni de balises — retourne \
uniquement le prompt final en markdown.

Source :

{source}
"""

_ORCHESTRATOR_PROMPT_TEMPLATE = """\
Tu reformules un prompt système d'agent IA (écrit à la deuxième personne \
du singulier) en une description à la troisième personne, utilisée par un \
orchestrateur pour décider quand dispatcher cet agent. Garde le sens exact, \
réécris en "Il est...", "Il analyse...", etc. Ne change pas les capacités \
décrites. Retourne uniquement la description finale.

Prompt original :

{source}
"""


async def _get_anthropic_client() -> anthropic.AsyncAnthropic:
    env = await secrets_service.resolve_env(["ANTHROPIC_API_KEY"])
    return anthropic.AsyncAnthropic(api_key=env["ANTHROPIC_API_KEY"])


async def generate_prompts(
    role: RoleSummary, documents: list[DocumentSummary]
) -> GeneratedPrompts:
    """Generate 2nd-person and 3rd-person prompt variants using Claude."""
    try:
        client = await _get_anthropic_client()
    except secrets_service.SecretNotFoundError as exc:
        raise MissingAnthropicKeyError(
            "ANTHROPIC_API_KEY is not set in Module 0 (Secrets)"
        ) from exc

    source = assemble_source_markdown(role, documents)

    _log.info("prompt_generator.agent.start", role_id=role.id)
    agent_response = await client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=role.max_tokens,
        messages=[
            {
                "role": "user",
                "content": _AGENT_PROMPT_TEMPLATE.format(source=source),
            }
        ],
    )
    agent_text = agent_response.content[0].text  # type: ignore[union-attr]

    _log.info("prompt_generator.orchestrator.start", role_id=role.id)
    orch_response = await client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=role.max_tokens,
        messages=[
            {
                "role": "user",
                "content": _ORCHESTRATOR_PROMPT_TEMPLATE.format(source=agent_text),
            }
        ],
    )
    orch_text = orch_response.content[0].text  # type: ignore[union-attr]

    _log.info("prompt_generator.done", role_id=role.id)
    return GeneratedPrompts(
        prompt_agent_md=agent_text,
        prompt_orchestrator_md=orch_text,
    )
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run python -m pytest tests/test_prompt_generator.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/agflow/services/prompt_generator.py backend/tests/test_prompt_generator.py
git commit -m "feat(m2): prompt_generator using Anthropic via secrets_service"
```

---

### Task 6: Admin router `/api/admin/roles/*`

**Files:**
- Create: `backend/src/agflow/api/admin/roles.py`
- Create: `backend/tests/test_roles_endpoint.py`
- Modify: `backend/src/agflow/main.py`

- [ ] **Step 1: Write failing endpoint tests**

Create `backend/tests/test_roles_endpoint.py`:

```python
from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from agflow.db.migrations import run_migrations
from agflow.db.pool import close_pool, execute
from agflow.main import create_app
from agflow.services import prompt_generator

_MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    await execute("DROP TABLE IF EXISTS role_documents CASCADE")
    await execute("DROP TABLE IF EXISTS roles CASCADE")
    await execute("DROP TABLE IF EXISTS secrets CASCADE")
    await execute("DROP TABLE IF EXISTS schema_migrations CASCADE")
    await run_migrations(_MIGRATIONS_DIR)

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c

    await close_pool()


async def _token(client: AsyncClient) -> dict[str, str]:
    res = await client.post(
        "/api/admin/auth/login",
        json={"email": "admin@example.com", "password": "correct-password"},
    )
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.mark.asyncio
async def test_create_role_and_list(client: AsyncClient) -> None:
    headers = await _token(client)

    create = await client.post(
        "/api/admin/roles",
        headers=headers,
        json={"id": "analyst", "display_name": "Analyst"},
    )
    assert create.status_code == 201, create.text
    assert create.json()["id"] == "analyst"

    listing = await client.get("/api/admin/roles", headers=headers)
    assert listing.status_code == 200
    assert any(r["id"] == "analyst" for r in listing.json())


@pytest.mark.asyncio
async def test_get_role_detail_includes_documents(client: AsyncClient) -> None:
    headers = await _token(client)

    await client.post(
        "/api/admin/roles",
        headers=headers,
        json={"id": "analyst", "display_name": "Analyst"},
    )
    await client.post(
        "/api/admin/roles/analyst/documents",
        headers=headers,
        json={"section": "roles", "name": "r1", "content_md": "Tu analyses."},
    )
    await client.post(
        "/api/admin/roles/analyst/documents",
        headers=headers,
        json={"section": "missions", "name": "m1", "content_md": "Tu transformes."},
    )

    res = await client.get("/api/admin/roles/analyst", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["role"]["id"] == "analyst"
    assert len(body["roles_documents"]) == 1
    assert len(body["missions_documents"]) == 1
    assert len(body["competences_documents"]) == 0


@pytest.mark.asyncio
async def test_update_and_delete_role(client: AsyncClient) -> None:
    headers = await _token(client)

    await client.post(
        "/api/admin/roles",
        headers=headers,
        json={"id": "tmp", "display_name": "Tmp"},
    )

    upd = await client.put(
        "/api/admin/roles/tmp",
        headers=headers,
        json={"display_name": "Updated"},
    )
    assert upd.status_code == 200
    assert upd.json()["display_name"] == "Updated"

    delres = await client.delete("/api/admin/roles/tmp", headers=headers)
    assert delres.status_code == 204

    listing = await client.get("/api/admin/roles", headers=headers)
    assert all(r["id"] != "tmp" for r in listing.json())


@pytest.mark.asyncio
async def test_document_protected_flag_blocks_update(client: AsyncClient) -> None:
    headers = await _token(client)

    await client.post(
        "/api/admin/roles",
        headers=headers,
        json={"id": "r1", "display_name": "R1"},
    )
    create_doc = await client.post(
        "/api/admin/roles/r1/documents",
        headers=headers,
        json={
            "section": "roles",
            "name": "locked",
            "content_md": "original",
            "protected": True,
        },
    )
    doc_id = create_doc.json()["id"]

    blocked = await client.put(
        f"/api/admin/roles/r1/documents/{doc_id}",
        headers=headers,
        json={"content_md": "should fail"},
    )
    assert blocked.status_code == 403


@pytest.mark.asyncio
async def test_generate_prompts_uses_mocked_anthropic(client: AsyncClient) -> None:
    headers = await _token(client)

    await client.post(
        "/api/admin/roles",
        headers=headers,
        json={
            "id": "gen",
            "display_name": "Gen",
            "identity_md": "Tu es rigoureux.",
        },
    )

    mock_result = prompt_generator.GeneratedPrompts(
        prompt_agent_md="Tu es un assistant rigoureux et direct.",
        prompt_orchestrator_md="Il est un assistant rigoureux et direct.",
    )

    with patch(
        "agflow.api.admin.roles.prompt_generator.generate_prompts",
        new=AsyncMock(return_value=mock_result),
    ):
        res = await client.post(
            "/api/admin/roles/gen/generate-prompts",
            headers=headers,
        )

    assert res.status_code == 200
    body = res.json()
    assert body["prompt_agent_md"].startswith("Tu es")
    assert body["prompt_orchestrator_md"].startswith("Il est")


@pytest.mark.asyncio
async def test_generate_prompts_missing_anthropic_key(client: AsyncClient) -> None:
    headers = await _token(client)

    await client.post(
        "/api/admin/roles",
        headers=headers,
        json={"id": "nokey", "display_name": "NoKey"},
    )

    with patch(
        "agflow.api.admin.roles.prompt_generator.generate_prompts",
        new=AsyncMock(
            side_effect=prompt_generator.MissingAnthropicKeyError(
                "ANTHROPIC_API_KEY is not set"
            )
        ),
    ):
        res = await client.post(
            "/api/admin/roles/nokey/generate-prompts",
            headers=headers,
        )

    assert res.status_code == 412  # Precondition Failed
    assert "ANTHROPIC_API_KEY" in res.json()["detail"]
```

- [ ] **Step 2: Run — expect 404**

Run: `cd backend && uv run python -m pytest tests/test_roles_endpoint.py -v`
Expected: many failures with 404.

- [ ] **Step 3: Implement the router**

Create `backend/src/agflow/api/admin/roles.py`:

```python
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from agflow.auth.dependencies import require_admin
from agflow.schemas.roles import (
    DocumentCreate,
    DocumentSummary,
    DocumentUpdate,
    RoleCreate,
    RoleDetail,
    RoleSummary,
    RoleUpdate,
)
from agflow.services import prompt_generator, role_documents_service, roles_service

router = APIRouter(
    prefix="/api/admin/roles",
    tags=["admin-roles"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[RoleSummary])
async def list_roles() -> list[RoleSummary]:
    return await roles_service.list_all()


@router.post("", response_model=RoleSummary, status_code=status.HTTP_201_CREATED)
async def create_role(payload: RoleCreate) -> RoleSummary:
    try:
        return await roles_service.create(
            role_id=payload.id,
            display_name=payload.display_name,
            description=payload.description,
            llm_type=payload.llm_type,
            temperature=payload.temperature,
            max_tokens=payload.max_tokens,
            service_types=payload.service_types,
            identity_md=payload.identity_md,
        )
    except roles_service.DuplicateRoleError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc


@router.get("/{role_id}", response_model=RoleDetail)
async def get_role(role_id: str) -> RoleDetail:
    try:
        role = await roles_service.get_by_id(role_id)
    except roles_service.RoleNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    documents = await role_documents_service.list_for_role(role_id)
    return RoleDetail(
        role=role,
        roles_documents=[d for d in documents if d.section == "roles"],
        missions_documents=[d for d in documents if d.section == "missions"],
        competences_documents=[d for d in documents if d.section == "competences"],
    )


@router.put("/{role_id}", response_model=RoleSummary)
async def update_role(role_id: str, payload: RoleUpdate) -> RoleSummary:
    try:
        return await roles_service.update(
            role_id, **payload.model_dump(exclude_unset=True)
        )
    except roles_service.RoleNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(role_id: str) -> None:
    try:
        await roles_service.delete(role_id)
    except roles_service.RoleNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.post("/{role_id}/generate-prompts", response_model=RoleSummary)
async def generate_prompts(role_id: str) -> RoleSummary:
    try:
        role = await roles_service.get_by_id(role_id)
    except roles_service.RoleNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    documents = await role_documents_service.list_for_role(role_id)
    try:
        generated = await prompt_generator.generate_prompts(role, documents)
    except prompt_generator.MissingAnthropicKeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_412_PRECONDITION_FAILED, detail=str(exc)
        ) from exc

    return await roles_service.update_prompts(
        role_id,
        prompt_agent_md=generated.prompt_agent_md,
        prompt_orchestrator_md=generated.prompt_orchestrator_md,
    )


@router.get("/{role_id}/documents", response_model=list[DocumentSummary])
async def list_documents(role_id: str) -> list[DocumentSummary]:
    return await role_documents_service.list_for_role(role_id)


@router.post(
    "/{role_id}/documents",
    response_model=DocumentSummary,
    status_code=status.HTTP_201_CREATED,
)
async def create_document(role_id: str, payload: DocumentCreate) -> DocumentSummary:
    try:
        return await role_documents_service.create(
            role_id=role_id,
            section=payload.section,
            name=payload.name,
            content_md=payload.content_md,
            protected=payload.protected,
        )
    except role_documents_service.DuplicateDocumentError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc


@router.put("/{role_id}/documents/{doc_id}", response_model=DocumentSummary)
async def update_document(
    role_id: str, doc_id: UUID, payload: DocumentUpdate
) -> DocumentSummary:
    try:
        return await role_documents_service.update(
            doc_id, content_md=payload.content_md, protected=payload.protected
        )
    except role_documents_service.DocumentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except role_documents_service.ProtectedDocumentError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc


@router.delete(
    "/{role_id}/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_document(role_id: str, doc_id: UUID) -> None:
    try:
        await role_documents_service.delete(doc_id)
    except role_documents_service.DocumentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except role_documents_service.ProtectedDocumentError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)
        ) from exc
```

- [ ] **Step 4: Register the router in `main.py`**

Edit `backend/src/agflow/main.py`:
```python
from agflow.api.admin.roles import router as admin_roles_router
```

In `create_app()`:
```python
    app.include_router(admin_roles_router)
```

- [ ] **Step 5: Run tests**

Run: `cd backend && uv run python -m pytest tests/test_roles_endpoint.py -v`
Expected: 6 passed.

- [ ] **Step 6: Full backend suite**

Run: `cd backend && uv run python -m pytest -q`
Expected: all tests green (34 previous + 25 new ≈ 59).

- [ ] **Step 7: Commit**

```bash
git add backend/src/agflow/api/admin/roles.py backend/src/agflow/main.py backend/tests/test_roles_endpoint.py
git commit -m "feat(m2): admin roles router + endpoint tests"
```

---

### Task 7: Frontend i18n + rolesApi client

**Files:**
- Modify: `frontend/src/i18n/fr.json`
- Modify: `frontend/src/i18n/en.json`
- Create: `frontend/src/lib/rolesApi.ts`

- [ ] **Step 1: Add i18n keys (fr)**

Edit `frontend/src/i18n/fr.json`, add after the `secrets` section:

```json
  "roles": {
    "page_title": "Rôles (personnalités d'agents)",
    "page_subtitle": "Identité, facettes, missions et compétences composables",
    "add_button": "+ Ajouter un rôle",
    "delete_button": "Supprimer le rôle",
    "no_roles": "Aucun rôle — crée ton premier rôle",
    "select_role": "Sélectionne un rôle",
    "tab_general": "Général",
    "tab_identity": "Identité",
    "tab_prompt": "Prompt",
    "tab_chat": "Chat",
    "chat_placeholder": "Co-construction avec LLM — disponible dans une phase future",
    "general": {
      "id": "ID (slug)",
      "display_name": "Nom d'affichage",
      "description": "Description",
      "llm_type": "Type LLM",
      "llm_single": "Single",
      "llm_multi": "Multi",
      "temperature": "Temperature",
      "max_tokens": "Max tokens",
      "service_types": "Types de services",
      "service_documentation": "Documentation",
      "service_code": "Code",
      "service_design": "Maquette/Design",
      "service_automation": "Automatisme",
      "service_task_list": "Liste de tâches",
      "service_specs": "Spécifications",
      "service_contract": "Contrat"
    },
    "identity": {
      "label": "Texte d'identité (2e personne)",
      "placeholder": "Tu es un assistant qui agit en tant que..."
    },
    "prompt": {
      "regenerate_button": "Régénérer les prompts",
      "generating": "Génération en cours…",
      "agent_title": "Prompt agent (2e personne)",
      "orchestrator_title": "Prompt orchestrateur (3e personne)",
      "empty": "Pas encore généré. Clique sur « Régénérer les prompts »."
    },
    "sidebar": {
      "roles_section": "ROLES",
      "missions_section": "MISSIONS",
      "competences_section": "COMPETENCES",
      "add_document": "+ Ajouter",
      "new_document_name": "Nom du document",
      "protected": "Verrouillé",
      "unlock": "Déverrouiller"
    },
    "errors": {
      "missing_anthropic_key": "ANTHROPIC_API_KEY manquante dans Module 0 (Secrets). Ajoute-la avant de générer les prompts.",
      "duplicate_id": "Un rôle avec cet ID existe déjà",
      "protected": "Document verrouillé — déverrouille-le pour modifier",
      "generic": "Une erreur est survenue"
    },
    "save": "Enregistrer",
    "saving": "Enregistrement…",
    "saved": "Enregistré"
  }
```

Make sure you add a comma after the closing brace of `secrets`.

- [ ] **Step 2: Add i18n keys (en)**

Edit `frontend/src/i18n/en.json` identically with English values (see fr.json as the canonical source and translate all keys).

- [ ] **Step 3: Create the typed API client**

Create `frontend/src/lib/rolesApi.ts`:

```ts
import { api } from "./api";

export type LLMType = "single" | "multi";
export type Section = "roles" | "missions" | "competences";

export interface RoleSummary {
  id: string;
  display_name: string;
  description: string;
  llm_type: LLMType;
  temperature: number;
  max_tokens: number;
  service_types: string[];
  identity_md: string;
  prompt_agent_md: string;
  prompt_orchestrator_md: string;
  runtime_config: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface DocumentSummary {
  id: string;
  role_id: string;
  section: Section;
  parent_path: string;
  name: string;
  content_md: string;
  protected: boolean;
  created_at: string;
  updated_at: string;
}

export interface RoleDetail {
  role: RoleSummary;
  roles_documents: DocumentSummary[];
  missions_documents: DocumentSummary[];
  competences_documents: DocumentSummary[];
}

export interface RoleCreate {
  id: string;
  display_name: string;
  description?: string;
  llm_type?: LLMType;
  temperature?: number;
  max_tokens?: number;
  service_types?: string[];
  identity_md?: string;
}

export interface RoleUpdate {
  display_name?: string;
  description?: string;
  llm_type?: LLMType;
  temperature?: number;
  max_tokens?: number;
  service_types?: string[];
  identity_md?: string;
}

export interface DocumentCreate {
  section: Section;
  name: string;
  content_md?: string;
  protected?: boolean;
}

export interface DocumentUpdate {
  content_md?: string;
  protected?: boolean;
}

export const rolesApi = {
  async list(): Promise<RoleSummary[]> {
    const res = await api.get<RoleSummary[]>("/admin/roles");
    return res.data;
  },
  async get(id: string): Promise<RoleDetail> {
    const res = await api.get<RoleDetail>(`/admin/roles/${id}`);
    return res.data;
  },
  async create(payload: RoleCreate): Promise<RoleSummary> {
    const res = await api.post<RoleSummary>("/admin/roles", payload);
    return res.data;
  },
  async update(id: string, payload: RoleUpdate): Promise<RoleSummary> {
    const res = await api.put<RoleSummary>(`/admin/roles/${id}`, payload);
    return res.data;
  },
  async remove(id: string): Promise<void> {
    await api.delete(`/admin/roles/${id}`);
  },
  async generatePrompts(id: string): Promise<RoleSummary> {
    const res = await api.post<RoleSummary>(`/admin/roles/${id}/generate-prompts`);
    return res.data;
  },
  async createDocument(
    roleId: string,
    payload: DocumentCreate,
  ): Promise<DocumentSummary> {
    const res = await api.post<DocumentSummary>(
      `/admin/roles/${roleId}/documents`,
      payload,
    );
    return res.data;
  },
  async updateDocument(
    roleId: string,
    docId: string,
    payload: DocumentUpdate,
  ): Promise<DocumentSummary> {
    const res = await api.put<DocumentSummary>(
      `/admin/roles/${roleId}/documents/${docId}`,
      payload,
    );
    return res.data;
  },
  async deleteDocument(roleId: string, docId: string): Promise<void> {
    await api.delete(`/admin/roles/${roleId}/documents/${docId}`);
  },
};
```

- [ ] **Step 4: Verify TS compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/i18n/fr.json frontend/src/i18n/en.json frontend/src/lib/rolesApi.ts
git commit -m "feat(m2): frontend i18n + rolesApi client"
```

---

### Task 8: `useRoles` + `useRoleDocuments` hooks (TDD)

**Files:**
- Create: `frontend/src/hooks/useRoles.ts`
- Create: `frontend/src/hooks/useRoleDocuments.ts`
- Create: `frontend/tests/hooks/useRoles.test.tsx`

- [ ] **Step 1: Write failing test for useRoles**

Create `frontend/tests/hooks/useRoles.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useRoles } from "@/hooks/useRoles";
import { rolesApi } from "@/lib/rolesApi";

vi.mock("@/lib/rolesApi", () => ({
  rolesApi: {
    list: vi.fn(),
    get: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    generatePrompts: vi.fn(),
    createDocument: vi.fn(),
    updateDocument: vi.fn(),
    deleteDocument: vi.fn(),
  },
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useRoles", () => {
  beforeEach(() => vi.clearAllMocks());

  it("loads roles via rolesApi.list", async () => {
    vi.mocked(rolesApi.list).mockResolvedValueOnce([
      {
        id: "analyst",
        display_name: "Analyst",
        description: "",
        llm_type: "single",
        temperature: 0.3,
        max_tokens: 4096,
        service_types: [],
        identity_md: "",
        prompt_agent_md: "",
        prompt_orchestrator_md: "",
        runtime_config: {},
        created_at: "2026-04-10",
        updated_at: "2026-04-10",
      },
    ]);

    const { result } = renderHook(() => useRoles(), { wrapper });

    await waitFor(() => expect(result.current.roles).toHaveLength(1));
    expect(result.current.roles?.[0]?.id).toBe("analyst");
  });

  it("creates a role via mutation", async () => {
    vi.mocked(rolesApi.list).mockResolvedValue([]);
    vi.mocked(rolesApi.create).mockResolvedValueOnce({
      id: "new",
      display_name: "New",
      description: "",
      llm_type: "single",
      temperature: 0.3,
      max_tokens: 4096,
      service_types: [],
      identity_md: "",
      prompt_agent_md: "",
      prompt_orchestrator_md: "",
      runtime_config: {},
      created_at: "2026-04-10",
      updated_at: "2026-04-10",
    });

    const { result } = renderHook(() => useRoles(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await result.current.createMutation.mutateAsync({
      id: "new",
      display_name: "New",
    });

    expect(rolesApi.create).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run — expect module not found**

Run: `cd frontend && npm test -- tests/hooks/useRoles.test.tsx`

- [ ] **Step 3: Implement `useRoles.ts`**

Create `frontend/src/hooks/useRoles.ts`:

```ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  rolesApi,
  type RoleCreate,
  type RoleSummary,
  type RoleUpdate,
} from "@/lib/rolesApi";

const ROLES_KEY = ["roles"] as const;

export function useRoles() {
  const qc = useQueryClient();

  const listQuery = useQuery<RoleSummary[]>({
    queryKey: ROLES_KEY,
    queryFn: () => rolesApi.list(),
  });

  const createMutation = useMutation({
    mutationFn: (payload: RoleCreate) => rolesApi.create(payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ROLES_KEY }),
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: RoleUpdate }) =>
      rolesApi.update(id, payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ROLES_KEY }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => rolesApi.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ROLES_KEY }),
  });

  const generateMutation = useMutation({
    mutationFn: (id: string) => rolesApi.generatePrompts(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ROLES_KEY }),
  });

  return {
    roles: listQuery.data,
    isLoading: listQuery.isLoading,
    error: listQuery.error,
    createMutation,
    updateMutation,
    deleteMutation,
    generateMutation,
  };
}
```

- [ ] **Step 4: Implement `useRoleDocuments.ts`**

Create `frontend/src/hooks/useRoleDocuments.ts`:

```ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  rolesApi,
  type DocumentCreate,
  type DocumentUpdate,
  type RoleDetail,
} from "@/lib/rolesApi";

export function useRoleDetail(roleId: string | null) {
  return useQuery<RoleDetail>({
    queryKey: ["role", roleId],
    queryFn: () => {
      if (!roleId) throw new Error("roleId required");
      return rolesApi.get(roleId);
    },
    enabled: !!roleId,
  });
}

export function useRoleDocumentMutations(roleId: string) {
  const qc = useQueryClient();
  const invalidate = () =>
    qc.invalidateQueries({ queryKey: ["role", roleId] });

  const createDoc = useMutation({
    mutationFn: (payload: DocumentCreate) =>
      rolesApi.createDocument(roleId, payload),
    onSuccess: invalidate,
  });

  const updateDoc = useMutation({
    mutationFn: ({ docId, payload }: { docId: string; payload: DocumentUpdate }) =>
      rolesApi.updateDocument(roleId, docId, payload),
    onSuccess: invalidate,
  });

  const deleteDoc = useMutation({
    mutationFn: (docId: string) => rolesApi.deleteDocument(roleId, docId),
    onSuccess: invalidate,
  });

  return { createDoc, updateDoc, deleteDoc };
}
```

- [ ] **Step 5: Run tests**

Run: `cd frontend && npm test -- tests/hooks/useRoles.test.tsx`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/hooks/useRoles.ts frontend/src/hooks/useRoleDocuments.ts frontend/tests/hooks/useRoles.test.tsx
git commit -m "feat(m2): useRoles + useRoleDocuments hooks with tests"
```

---

### Task 9: `MarkdownEditor` component (TDD)

**Files:**
- Create: `frontend/src/components/MarkdownEditor.tsx`
- Create: `frontend/tests/components/MarkdownEditor.test.tsx`

- [ ] **Step 1: Write failing test**

Create `frontend/tests/components/MarkdownEditor.test.tsx`:

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MarkdownEditor } from "@/components/MarkdownEditor";
import "@/lib/i18n";

describe("MarkdownEditor", () => {
  it("renders the initial value in the textarea", () => {
    render(
      <MarkdownEditor value="# Hello" onChange={vi.fn()} />,
    );
    expect(screen.getByRole("textbox")).toHaveValue("# Hello");
  });

  it("calls onChange with new value when typing", async () => {
    const onChange = vi.fn();
    render(<MarkdownEditor value="" onChange={onChange} />);

    await userEvent.type(screen.getByRole("textbox"), "abc");

    expect(onChange).toHaveBeenCalled();
    expect(onChange).toHaveBeenLastCalledWith("abc");
  });

  it("disables the textarea when readOnly is true", () => {
    render(<MarkdownEditor value="locked" onChange={vi.fn()} readOnly />);
    expect(screen.getByRole("textbox")).toBeDisabled();
  });
});
```

- [ ] **Step 2: Run — expect failure**

Run: `cd frontend && npm test -- tests/components/MarkdownEditor.test.tsx`

- [ ] **Step 3: Implement `MarkdownEditor.tsx`**

Create `frontend/src/components/MarkdownEditor.tsx`:

```tsx
import type { ChangeEvent } from "react";

interface Props {
  value: string;
  onChange: (value: string) => void;
  readOnly?: boolean;
  placeholder?: string;
  minHeight?: number;
}

export function MarkdownEditor({
  value,
  onChange,
  readOnly = false,
  placeholder,
  minHeight = 240,
}: Props) {
  function handleChange(e: ChangeEvent<HTMLTextAreaElement>) {
    onChange(e.target.value);
  }

  return (
    <textarea
      value={value}
      onChange={handleChange}
      disabled={readOnly}
      placeholder={placeholder}
      style={{
        width: "100%",
        minHeight: `${minHeight}px`,
        fontFamily: "ui-monospace, SFMono-Regular, monospace",
        fontSize: "13px",
        padding: "0.75rem",
        border: "1px solid #ccc",
        borderRadius: "4px",
        resize: "vertical",
      }}
    />
  );
}
```

- [ ] **Step 4: Run tests**

Run: `cd frontend && npm test -- tests/components/MarkdownEditor.test.tsx`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/MarkdownEditor.tsx frontend/tests/components/MarkdownEditor.test.tsx
git commit -m "feat(m2): MarkdownEditor component with tests"
```

---

### Task 10: `RoleSidebar` component (TDD)

**Files:**
- Create: `frontend/src/components/RoleSidebar.tsx`
- Create: `frontend/tests/components/RoleSidebar.test.tsx`

- [ ] **Step 1: Write failing test**

Create `frontend/tests/components/RoleSidebar.test.tsx`:

```tsx
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RoleSidebar } from "@/components/RoleSidebar";
import type { DocumentSummary } from "@/lib/rolesApi";
import "@/lib/i18n";

function makeDoc(overrides: Partial<DocumentSummary>): DocumentSummary {
  return {
    id: "id1",
    role_id: "r",
    section: "roles",
    parent_path: "",
    name: "doc1",
    content_md: "",
    protected: false,
    created_at: "2026-04-10",
    updated_at: "2026-04-10",
    ...overrides,
  };
}

describe("RoleSidebar", () => {
  it("renders sections with documents", () => {
    const documents = [
      makeDoc({ id: "r1", section: "roles", name: "analyse" }),
      makeDoc({ id: "m1", section: "missions", name: "transform" }),
      makeDoc({ id: "c1", section: "competences", name: "deduction" }),
    ];

    render(
      <RoleSidebar
        documents={documents}
        selectedDocId={null}
        onSelect={vi.fn()}
        onAdd={vi.fn()}
      />,
    );

    expect(screen.getByText("ROLES")).toBeInTheDocument();
    expect(screen.getByText("MISSIONS")).toBeInTheDocument();
    expect(screen.getByText("COMPETENCES")).toBeInTheDocument();
    expect(screen.getByText("analyse")).toBeInTheDocument();
    expect(screen.getByText("transform")).toBeInTheDocument();
    expect(screen.getByText("deduction")).toBeInTheDocument();
  });

  it("shows 🔒 icon for protected documents", () => {
    const documents = [
      makeDoc({ id: "p1", name: "locked", protected: true }),
    ];

    render(
      <RoleSidebar
        documents={documents}
        selectedDocId={null}
        onSelect={vi.fn()}
        onAdd={vi.fn()}
      />,
    );

    const row = screen.getByText("locked").closest("button");
    expect(row).toHaveTextContent("🔒");
  });

  it("calls onSelect when a document is clicked", async () => {
    const onSelect = vi.fn();
    const documents = [makeDoc({ id: "click", name: "clickable" })];

    render(
      <RoleSidebar
        documents={documents}
        selectedDocId={null}
        onSelect={onSelect}
        onAdd={vi.fn()}
      />,
    );

    await userEvent.click(screen.getByText("clickable"));
    expect(onSelect).toHaveBeenCalledWith("click");
  });

  it("calls onAdd with the section name when Add is clicked", async () => {
    const onAdd = vi.fn();
    render(
      <RoleSidebar
        documents={[]}
        selectedDocId={null}
        onSelect={vi.fn()}
        onAdd={onAdd}
      />,
    );

    const addButtons = screen.getAllByRole("button", { name: /Ajouter/ });
    await userEvent.click(addButtons[0]!);
    expect(onAdd).toHaveBeenCalledWith("roles");
  });
});
```

- [ ] **Step 2: Run — expect failure**

- [ ] **Step 3: Implement `RoleSidebar.tsx`**

Create `frontend/src/components/RoleSidebar.tsx`:

```tsx
import { useTranslation } from "react-i18next";
import type { DocumentSummary, Section } from "@/lib/rolesApi";

interface Props {
  documents: DocumentSummary[];
  selectedDocId: string | null;
  onSelect: (docId: string) => void;
  onAdd: (section: Section) => void;
}

const SECTIONS: Section[] = ["roles", "missions", "competences"];

export function RoleSidebar({ documents, selectedDocId, onSelect, onAdd }: Props) {
  const { t } = useTranslation();

  return (
    <aside
      style={{
        minWidth: 260,
        borderRight: "1px solid #ddd",
        padding: "1rem",
      }}
    >
      {SECTIONS.map((section) => {
        const docs = documents.filter((d) => d.section === section);
        const title = t(`roles.sidebar.${section}_section`);
        return (
          <div key={section} style={{ marginBottom: "1.25rem" }}>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                fontWeight: 600,
                fontSize: "11px",
                letterSpacing: "0.05em",
                color: "#666",
                marginBottom: "0.5rem",
              }}
            >
              <span>{title}</span>
              <button
                type="button"
                onClick={() => onAdd(section)}
                style={{
                  fontSize: "11px",
                  padding: "2px 6px",
                  cursor: "pointer",
                }}
              >
                {t("roles.sidebar.add_document")}
              </button>
            </div>
            {docs.length === 0 ? (
              <div style={{ fontSize: "12px", color: "#999", fontStyle: "italic" }}>
                —
              </div>
            ) : (
              <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
                {docs.map((doc) => (
                  <li key={doc.id}>
                    <button
                      type="button"
                      onClick={() => onSelect(doc.id)}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "0.5rem",
                        width: "100%",
                        padding: "4px 6px",
                        textAlign: "left",
                        border: "none",
                        background:
                          selectedDocId === doc.id ? "#e0e7ff" : "transparent",
                        cursor: "pointer",
                        fontSize: "13px",
                      }}
                    >
                      <span>{doc.protected ? "🔒" : "📄"}</span>
                      <span>{doc.name}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        );
      })}
    </aside>
  );
}
```

- [ ] **Step 4: Run tests**

Run: `cd frontend && npm test -- tests/components/RoleSidebar.test.tsx`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/RoleSidebar.tsx frontend/tests/components/RoleSidebar.test.tsx
git commit -m "feat(m2): RoleSidebar component with tests"
```

---

### Task 11: Role tabs (General / Identity / Prompt)

**Files:**
- Create: `frontend/src/components/RoleGeneralTab.tsx`
- Create: `frontend/src/components/RoleIdentityTab.tsx`
- Create: `frontend/src/components/RolePromptTab.tsx`

*(These components are pure presentational + controlled by parent state. No test required at this granularity — they're exercised via the RolesPage test in Task 12.)*

- [ ] **Step 1: Implement `RoleGeneralTab.tsx`**

Create `frontend/src/components/RoleGeneralTab.tsx`:

```tsx
import { useTranslation } from "react-i18next";
import type { LLMType, RoleSummary } from "@/lib/rolesApi";

interface Props {
  role: RoleSummary;
  onChange: (updates: Partial<RoleSummary>) => void;
}

const SERVICE_TYPES = [
  "documentation",
  "code",
  "design",
  "automation",
  "task_list",
  "specs",
  "contract",
] as const;

export function RoleGeneralTab({ role, onChange }: Props) {
  const { t } = useTranslation();

  function toggleService(service: string) {
    const current = role.service_types ?? [];
    const next = current.includes(service)
      ? current.filter((s) => s !== service)
      : [...current, service];
    onChange({ service_types: next });
  }

  return (
    <div style={{ maxWidth: 640, display: "flex", flexDirection: "column", gap: "1rem" }}>
      <div>
        <label>
          <strong>{t("roles.general.id")}</strong>
          <input type="text" value={role.id} disabled style={{ display: "block", width: "100%" }} />
        </label>
      </div>
      <div>
        <label>
          <strong>{t("roles.general.display_name")}</strong>
          <input
            type="text"
            value={role.display_name}
            onChange={(e) => onChange({ display_name: e.target.value })}
            style={{ display: "block", width: "100%" }}
          />
        </label>
      </div>
      <div>
        <label>
          <strong>{t("roles.general.description")}</strong>
          <textarea
            value={role.description}
            onChange={(e) => onChange({ description: e.target.value })}
            style={{ display: "block", width: "100%", minHeight: "80px" }}
          />
        </label>
      </div>
      <div style={{ display: "flex", gap: "1rem" }}>
        <label>
          <strong>{t("roles.general.llm_type")}</strong>
          <select
            value={role.llm_type}
            onChange={(e) => onChange({ llm_type: e.target.value as LLMType })}
            style={{ display: "block" }}
          >
            <option value="single">{t("roles.general.llm_single")}</option>
            <option value="multi">{t("roles.general.llm_multi")}</option>
          </select>
        </label>
        <label>
          <strong>{t("roles.general.temperature")}</strong>
          <input
            type="number"
            step="0.1"
            min="0"
            max="2"
            value={role.temperature}
            onChange={(e) => onChange({ temperature: parseFloat(e.target.value) })}
            style={{ display: "block", width: "100px" }}
          />
        </label>
        <label>
          <strong>{t("roles.general.max_tokens")}</strong>
          <input
            type="number"
            step="256"
            min="1"
            value={role.max_tokens}
            onChange={(e) => onChange({ max_tokens: parseInt(e.target.value, 10) })}
            style={{ display: "block", width: "120px" }}
          />
        </label>
      </div>
      <div>
        <strong>{t("roles.general.service_types")}</strong>
        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem", marginTop: "0.5rem" }}>
          {SERVICE_TYPES.map((service) => (
            <label key={service} style={{ fontSize: "13px" }}>
              <input
                type="checkbox"
                checked={role.service_types.includes(service)}
                onChange={() => toggleService(service)}
              />{" "}
              {t(`roles.general.service_${service}`)}
            </label>
          ))}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Implement `RoleIdentityTab.tsx`**

Create `frontend/src/components/RoleIdentityTab.tsx`:

```tsx
import { useTranslation } from "react-i18next";
import { MarkdownEditor } from "./MarkdownEditor";

interface Props {
  value: string;
  onChange: (value: string) => void;
}

export function RoleIdentityTab({ value, onChange }: Props) {
  const { t } = useTranslation();
  return (
    <div>
      <p>
        <strong>{t("roles.identity.label")}</strong>
      </p>
      <MarkdownEditor
        value={value}
        onChange={onChange}
        placeholder={t("roles.identity.placeholder")}
        minHeight={320}
      />
    </div>
  );
}
```

- [ ] **Step 3: Implement `RolePromptTab.tsx`**

Create `frontend/src/components/RolePromptTab.tsx`:

```tsx
import { useTranslation } from "react-i18next";
import { MarkdownEditor } from "./MarkdownEditor";
import type { RoleSummary } from "@/lib/rolesApi";

interface Props {
  role: RoleSummary;
  onRegenerate: () => void;
  regenerating: boolean;
  error: string | null;
}

export function RolePromptTab({
  role,
  onRegenerate,
  regenerating,
  error,
}: Props) {
  const { t } = useTranslation();

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "1.25rem" }}>
      <div>
        <button type="button" onClick={onRegenerate} disabled={regenerating}>
          {regenerating ? t("roles.prompt.generating") : t("roles.prompt.regenerate_button")}
        </button>
        {error && (
          <p role="alert" style={{ color: "red", marginTop: "0.5rem" }}>
            {error}
          </p>
        )}
      </div>
      <div>
        <h3>{t("roles.prompt.agent_title")}</h3>
        {role.prompt_agent_md ? (
          <MarkdownEditor value={role.prompt_agent_md} onChange={() => {}} readOnly />
        ) : (
          <p style={{ color: "#888", fontStyle: "italic" }}>{t("roles.prompt.empty")}</p>
        )}
      </div>
      <div>
        <h3>{t("roles.prompt.orchestrator_title")}</h3>
        {role.prompt_orchestrator_md ? (
          <MarkdownEditor
            value={role.prompt_orchestrator_md}
            onChange={() => {}}
            readOnly
          />
        ) : (
          <p style={{ color: "#888", fontStyle: "italic" }}>{t("roles.prompt.empty")}</p>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Verify TS compiles**

Run: `cd frontend && npx tsc --noEmit`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/RoleGeneralTab.tsx frontend/src/components/RoleIdentityTab.tsx frontend/src/components/RolePromptTab.tsx
git commit -m "feat(m2): RoleGeneralTab + RoleIdentityTab + RolePromptTab"
```

---

### Task 12: `RolesPage` — layout + integration (TDD)

**Files:**
- Create: `frontend/src/pages/RolesPage.tsx`
- Create: `frontend/tests/pages/RolesPage.test.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/pages/HomePage.tsx`

- [ ] **Step 1: Write failing test for RolesPage**

Create `frontend/tests/pages/RolesPage.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RolesPage } from "@/pages/RolesPage";
import { rolesApi } from "@/lib/rolesApi";
import "@/lib/i18n";

vi.mock("@/lib/rolesApi", () => ({
  rolesApi: {
    list: vi.fn(),
    get: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    remove: vi.fn(),
    generatePrompts: vi.fn(),
    createDocument: vi.fn(),
    updateDocument: vi.fn(),
    deleteDocument: vi.fn(),
  },
}));

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <RolesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("RolesPage", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows empty state when no roles", async () => {
    vi.mocked(rolesApi.list).mockResolvedValueOnce([]);
    renderPage();
    expect(await screen.findByText(/Aucun rôle/)).toBeInTheDocument();
  });

  it("lists roles and shows add button", async () => {
    vi.mocked(rolesApi.list).mockResolvedValueOnce([
      {
        id: "analyst",
        display_name: "Analyst",
        description: "",
        llm_type: "single",
        temperature: 0.3,
        max_tokens: 4096,
        service_types: [],
        identity_md: "",
        prompt_agent_md: "",
        prompt_orchestrator_md: "",
        runtime_config: {},
        created_at: "2026-04-10",
        updated_at: "2026-04-10",
      },
    ]);

    renderPage();

    expect(await screen.findByText("Analyst")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Ajouter un rôle/ }),
    ).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run — expect failure**

- [ ] **Step 3: Implement `RolesPage.tsx`**

Create `frontend/src/pages/RolesPage.tsx`:

```tsx
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useRoles } from "@/hooks/useRoles";
import {
  useRoleDetail,
  useRoleDocumentMutations,
} from "@/hooks/useRoleDocuments";
import { RoleSidebar } from "@/components/RoleSidebar";
import { RoleGeneralTab } from "@/components/RoleGeneralTab";
import { RoleIdentityTab } from "@/components/RoleIdentityTab";
import { RolePromptTab } from "@/components/RolePromptTab";
import { MarkdownEditor } from "@/components/MarkdownEditor";
import type { RoleSummary, Section } from "@/lib/rolesApi";

type Tab = "general" | "identity" | "prompt" | "chat";

export function RolesPage() {
  const { t } = useTranslation();
  const {
    roles,
    isLoading,
    createMutation,
    updateMutation,
    deleteMutation,
    generateMutation,
  } = useRoles();

  const [selectedRoleId, setSelectedRoleId] = useState<string | null>(null);
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("general");
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [draftRole, setDraftRole] = useState<RoleSummary | null>(null);

  const detail = useRoleDetail(selectedRoleId);
  const docMutations = useRoleDocumentMutations(selectedRoleId ?? "");

  const currentRole = draftRole ?? detail.data?.role ?? null;
  const allDocuments = detail.data
    ? [
        ...detail.data.roles_documents,
        ...detail.data.missions_documents,
        ...detail.data.competences_documents,
      ]
    : [];
  const selectedDoc = allDocuments.find((d) => d.id === selectedDocId) ?? null;

  async function handleCreateRole() {
    const id = window.prompt(t("roles.general.id"));
    if (!id) return;
    const display_name = window.prompt(t("roles.general.display_name")) ?? id;
    const created = await createMutation.mutateAsync({ id, display_name });
    setSelectedRoleId(created.id);
    setTab("general");
  }

  async function handleDeleteRole() {
    if (!selectedRoleId) return;
    if (!window.confirm(`${t("roles.delete_button")} "${selectedRoleId}"?`))
      return;
    await deleteMutation.mutateAsync(selectedRoleId);
    setSelectedRoleId(null);
    setDraftRole(null);
  }

  async function handleSaveRole() {
    if (!draftRole || !selectedRoleId) return;
    await updateMutation.mutateAsync({
      id: selectedRoleId,
      payload: {
        display_name: draftRole.display_name,
        description: draftRole.description,
        llm_type: draftRole.llm_type,
        temperature: draftRole.temperature,
        max_tokens: draftRole.max_tokens,
        service_types: draftRole.service_types,
        identity_md: draftRole.identity_md,
      },
    });
    setDraftRole(null);
  }

  async function handleGenerate() {
    if (!selectedRoleId) return;
    setGenerateError(null);
    try {
      await generateMutation.mutateAsync(selectedRoleId);
    } catch (err: unknown) {
      const detailText =
        (err as { response?: { data?: { detail?: string }; status?: number } })
          .response?.data?.detail ?? t("roles.errors.generic");
      const status = (err as { response?: { status?: number } }).response?.status;
      if (status === 412) {
        setGenerateError(t("roles.errors.missing_anthropic_key"));
      } else {
        setGenerateError(detailText);
      }
    }
  }

  async function handleAddDocument(section: Section) {
    if (!selectedRoleId) return;
    const name = window.prompt(t("roles.sidebar.new_document_name"));
    if (!name) return;
    const doc = await docMutations.createDoc.mutateAsync({
      section,
      name,
      content_md: "",
      protected: false,
    });
    setSelectedDocId(doc.id);
  }

  async function handleDocumentChange(content: string) {
    if (!selectedDoc || !selectedRoleId) return;
    await docMutations.updateDoc.mutateAsync({
      docId: selectedDoc.id,
      payload: { content_md: content },
    });
  }

  function handleRoleFieldChange(updates: Partial<RoleSummary>) {
    if (!currentRole) return;
    setDraftRole({ ...currentRole, ...updates });
  }

  if (isLoading) return <p>{t("secrets.loading")}</p>;

  return (
    <div style={{ display: "flex", height: "100vh" }}>
      <aside
        style={{
          minWidth: 240,
          borderRight: "1px solid #ddd",
          padding: "1rem",
          background: "#fafafa",
        }}
      >
        <h2>{t("roles.page_title")}</h2>
        <button type="button" onClick={handleCreateRole}>
          {t("roles.add_button")}
        </button>
        {(roles ?? []).length === 0 ? (
          <p style={{ color: "#999", fontStyle: "italic" }}>
            {t("roles.no_roles")}
          </p>
        ) : (
          <ul style={{ listStyle: "none", padding: 0, marginTop: "1rem" }}>
            {roles?.map((r) => (
              <li key={r.id}>
                <button
                  type="button"
                  onClick={() => {
                    setSelectedRoleId(r.id);
                    setSelectedDocId(null);
                    setDraftRole(null);
                  }}
                  style={{
                    width: "100%",
                    textAlign: "left",
                    padding: "6px",
                    background:
                      selectedRoleId === r.id ? "#e0e7ff" : "transparent",
                    border: "none",
                    cursor: "pointer",
                  }}
                >
                  {r.display_name}
                </button>
              </li>
            ))}
          </ul>
        )}
        {selectedRoleId && (
          <button
            type="button"
            onClick={handleDeleteRole}
            style={{ marginTop: "2rem", color: "red" }}
          >
            {t("roles.delete_button")}
          </button>
        )}
      </aside>

      {selectedRoleId && detail.data && currentRole ? (
        <>
          <RoleSidebar
            documents={allDocuments}
            selectedDocId={selectedDocId}
            onSelect={setSelectedDocId}
            onAdd={handleAddDocument}
          />
          <main style={{ flex: 1, padding: "1.5rem", overflowY: "auto" }}>
            <nav style={{ marginBottom: "1rem", display: "flex", gap: "1rem" }}>
              {(["general", "identity", "prompt", "chat"] as Tab[]).map((name) => (
                <button
                  key={name}
                  type="button"
                  onClick={() => {
                    setTab(name);
                    setSelectedDocId(null);
                  }}
                  style={{
                    fontWeight: tab === name ? 700 : 400,
                    border: "none",
                    background: "none",
                    cursor: "pointer",
                  }}
                >
                  {t(`roles.tab_${name}`)}
                </button>
              ))}
            </nav>

            {selectedDoc ? (
              <div>
                <h3>{selectedDoc.name}</h3>
                <MarkdownEditor
                  value={selectedDoc.content_md}
                  onChange={handleDocumentChange}
                  readOnly={selectedDoc.protected}
                />
              </div>
            ) : (
              <>
                {tab === "general" && (
                  <>
                    <RoleGeneralTab role={currentRole} onChange={handleRoleFieldChange} />
                    {draftRole && (
                      <button
                        type="button"
                        onClick={handleSaveRole}
                        style={{ marginTop: "1rem" }}
                      >
                        {t("roles.save")}
                      </button>
                    )}
                  </>
                )}
                {tab === "identity" && (
                  <>
                    <RoleIdentityTab
                      value={currentRole.identity_md}
                      onChange={(v) => handleRoleFieldChange({ identity_md: v })}
                    />
                    {draftRole && (
                      <button
                        type="button"
                        onClick={handleSaveRole}
                        style={{ marginTop: "1rem" }}
                      >
                        {t("roles.save")}
                      </button>
                    )}
                  </>
                )}
                {tab === "prompt" && (
                  <RolePromptTab
                    role={currentRole}
                    onRegenerate={handleGenerate}
                    regenerating={generateMutation.isPending}
                    error={generateError}
                  />
                )}
                {tab === "chat" && (
                  <p style={{ color: "#888", fontStyle: "italic" }}>
                    {t("roles.chat_placeholder")}
                  </p>
                )}
              </>
            )}
          </main>
        </>
      ) : (
        <main style={{ flex: 1, padding: "2rem", color: "#888" }}>
          <p>{t("roles.select_role")}</p>
        </main>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run tests**

Run: `cd frontend && npm test -- tests/pages/RolesPage.test.tsx`
Expected: 2 passed.

- [ ] **Step 5: Add `/roles` route in `App.tsx`**

Edit `frontend/src/App.tsx`, add import and route:

```tsx
import { RolesPage } from "./pages/RolesPage";
```

And in `<Routes>`:

```tsx
      <Route
        path="/roles"
        element={
          <ProtectedRoute>
            <RolesPage />
          </ProtectedRoute>
        }
      />
```

- [ ] **Step 6: Add nav link in HomePage**

Edit `frontend/src/pages/HomePage.tsx`, inside the `<nav>`:

```tsx
        <Link to="/secrets">{t("secrets.page_title")}</Link>
        {" • "}
        <Link to="/roles">{t("roles.page_title")}</Link>
```

- [ ] **Step 7: Full frontend suite + TS strict**

Run: `cd frontend && npm test && npx tsc --noEmit`
Expected: all tests green, no TS errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/pages/RolesPage.tsx frontend/src/App.tsx frontend/src/pages/HomePage.tsx frontend/tests/pages/RolesPage.test.tsx
git commit -m "feat(m2): RolesPage wired into router with nav link"
```

---

### Task 13: Deploy to LXC 201 + manual E2E smoke test

- [ ] **Step 1: Rebuild + deploy**

Run: `./scripts/deploy.sh --rebuild`
Expected: all 5 containers up.

- [ ] **Step 2: Apply migrations on prod**

Run:
```bash
ssh pve "pct exec 201 -- docker exec agflow-backend python -m agflow.db.migrations"
```
Expected: log shows `applied=['003_roles', '004_role_documents']` (or empty if already).

- [ ] **Step 3: Verify schema**

Run:
```bash
ssh pve "pct exec 201 -- docker exec agflow-postgres psql -U agflow -d agflow -c '\dt'"
```
Expected: listing shows `roles`, `role_documents`, `secrets`, `schema_migrations`.

- [ ] **Step 4: Smoke test via curl**

```bash
# Login
TOKEN=$(curl -s -X POST http://192.168.10.82/api/admin/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@agflow.example.com","password":"agflow-admin-2026"}' \
  | uv run python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Create a role
curl -s -X POST http://192.168.10.82/api/admin/roles \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"id":"smoke_analyst","display_name":"Smoke Analyst","identity_md":"Tu es un analyste rigoureux."}'

# Add a document
curl -s -X POST http://192.168.10.82/api/admin/roles/smoke_analyst/documents \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"section":"roles","name":"analyse","content_md":"Tu analyses et extrais."}'

# Fetch detail
curl -s -H "Authorization: Bearer $TOKEN" http://192.168.10.82/api/admin/roles/smoke_analyst
```

Expected: all 200/201 responses, detail shows 1 document in `roles_documents`.

- [ ] **Step 5: Browser walkthrough**

1. Open http://192.168.10.82/
2. Login as admin
3. Go to HomePage → click "Rôles (personnalités d'agents)"
4. See "smoke_analyst" in the left rail
5. Click it → see the 4 tabs (Général / Identité / Prompt / Chat)
6. Click "ROLES" + button → enter a new document name → content shows up
7. Edit the textarea → go to Identity tab → edit identity → click Save
8. Go to Prompt tab → click "Régénérer les prompts"
    - If `ANTHROPIC_API_KEY` is in Module 0 Secrets → 2 prompts generated and displayed
    - Otherwise → error message "ANTHROPIC_API_KEY manquante dans Module 0 (Secrets)"
9. Cleanup: delete the smoke_analyst role via the red "Supprimer le rôle" button

- [ ] **Step 6: Final push**

```bash
git push origin main
```

---

## Verification end-to-end

After all tasks pass:

```bash
# Backend: ~59 tests passed (34 previous + 25 new for M2)
cd backend && uv run python -m pytest -q
cd backend && uv run ruff check src/ tests/

# Frontend: ~28 tests passed (19 previous + ~9 new for M2)
cd frontend && npm test
cd frontend && npx tsc --noEmit

# LXC 201 prod smoke:
curl http://192.168.10.82/health  # → {"status":"ok"}
```

Browser walkthrough: login → /roles → create role → add documents → save → (optional) generate prompts → delete role.

---

## Self-Review Checklist

**1. Spec coverage (Module 2 requirements from specs/home.md):**
- ✅ ID (slug) + display_name + description — T2, T3
- ✅ LLM params (type, temperature, max_tokens) — T2, T3, T11
- ✅ Service types checkboxes (7 types) — T2, T11
- ✅ Identity in 2nd person — stored, edited, used in prompt assembly
- ✅ Auto-generated agent prompt (2nd person) — T5
- ✅ Auto-generated orchestrator prompt (3rd person) — T5
- ✅ Sidebar with ROLES / MISSIONS / COMPETENCES sections — T10
- ✅ 📄 / 🔒 icons for editable vs protected documents — T10
- ✅ Add button per section — T10
- ✅ Protected documents cannot be edited — backend enforced (T4 + endpoint test)
- ✅ Role dropdown / selector at top — T12 (left rail list)
- ✅ Add button + delete role button — T12
- ⚠ **Import button** — placeholder only (explicit non-goal)
- ⚠ **Chat tab (co-building with LLM)** — placeholder only (explicit non-goal)
- ⚠ **Directory grouping in sidebar** — schema supports `parent_path`, UI stays flat (explicit non-goal)
- ⚠ **Manual override of generated prompts** — Phase 2 overwrites on regenerate; hand-editing will come later

**2. Placeholder scan:** Every task has actual code, exact paths, and verification steps. Explicit non-goals are documented at the top and in the self-review.

**3. Type consistency:**
- Backend `RoleSummary` / `DocumentSummary` fields match frontend interfaces in `rolesApi.ts`.
- Frontend `Section` type matches backend `Section` Literal.
- `generate-prompts` returns `RoleSummary` (with new `prompt_agent_md` / `prompt_orchestrator_md`), consistent with `generateMutation` expected type.

---

## Execution Handoff

Ready to execute inline with `superpowers:executing-plans` when the user approves. Same workflow as Phase 1: task by task, commits between tasks, tests green before moving on. Expected duration: similar to M0 (~45-60 min of tool operations).
