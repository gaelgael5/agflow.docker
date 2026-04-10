# agflow.docker Phase 3 — Module 1 (Dockerfiles) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Module 1 (Dockerfiles) — CRUD the Docker image definitions for CLI agents (claude-code, aider, codex, …). Each dockerfile is a set of files (Dockerfile, entrypoint.sh, run.cmd.md, any other file) that together build a Docker image via `aiodocker`. The image tag is a deterministic hash of the content so rebuilds are skipped when nothing changed. End state: an admin can create a `claude-code` dockerfile in the UI, edit its files, click "Compiler" and watch the build logs stream in a modal, then see a 🟢 badge meaning the image is up to date.

**Architecture:** Backend exposes `/api/admin/dockerfiles/*` routes. Three tables: `dockerfiles` (entities), `dockerfile_files` (content), `dockerfile_builds` (history + logs). Build uses `aiodocker` talking to the host Docker daemon via `/var/run/docker.sock` (mounted into the backend container). The build runs async in a background task, logs are persisted as they arrive, the UI polls the build row to show progress. Hash = SHA256 of `Dockerfile` content + every `*.sh` file sorted by name. Frontend is a 3-column layout: dockerfiles list, files list for selected dockerfile, editor for selected file, plus a "Compiler" button that opens a log modal.

**Tech Stack:** Backend — aiodocker (already in deps), asyncpg, FastAPI BackgroundTasks, structlog, pytest. Frontend — React 18 + TS strict, @tanstack/react-query, i18next, textarea-based editor (Monaco deferred).

---

## Context

Phase 0-2 gave us the platform shell + Secrets + Roles. Module 1 is the first phase that actually **builds Docker images**, the first phase where the backend drives a real runtime (Docker) beyond CRUD. This unlocks M4 (agents) which will reference a dockerfile + a role + MCPs + skills. Without buildable images, no agent can run.

**What is NOT in this phase:**
- **Real-time SSE log streaming** — Phase 3 uses polling (`GET /builds/{id}` every 1-2s while status='running'). SSE can come later.
- **Monaco code editor** — simple `<textarea>` with monospace font. Monaco is a large bundle, not worth the cost yet.
- **Build queue / parallelism** — one build at a time per dockerfile. If user triggers a 2nd build while one is running, the endpoint returns 409.
- **Image cleanup / GC** — Module 6. Old images accumulate for now.
- **Parameter templating resolution (`${VAR:-default}`)** — parameters are stored as JSONB but used only in M4 when composing an agent. Module 1 stores them, doesn't expand them.
- **File upload / binary files** — only text content through the editor (text files only).
- **Directory nesting within a dockerfile** — all files live at the root (flat, one level).

---

## File Structure

### Backend — files created
- `backend/migrations/007_dockerfiles.sql`
- `backend/migrations/008_dockerfile_files.sql`
- `backend/migrations/009_dockerfile_builds.sql`
- `backend/src/agflow/schemas/dockerfiles.py`
- `backend/src/agflow/services/dockerfiles_service.py`
- `backend/src/agflow/services/dockerfile_files_service.py`
- `backend/src/agflow/services/build_service.py`
- `backend/src/agflow/api/admin/dockerfiles.py`
- `backend/tests/test_dockerfiles_service.py`
- `backend/tests/test_dockerfile_files_service.py`
- `backend/tests/test_build_service.py`
- `backend/tests/test_dockerfiles_endpoint.py`

### Backend — files modified
- `backend/src/agflow/main.py` — register router
- `docker-compose.prod.yml` — mount `/var/run/docker.sock` into backend service

### Frontend — files created
- `frontend/src/lib/dockerfilesApi.ts`
- `frontend/src/hooks/useDockerfiles.ts`
- `frontend/src/hooks/useBuild.ts`
- `frontend/src/components/DockerfileSidebar.tsx`
- `frontend/src/components/DockerfileFileList.tsx`
- `frontend/src/components/DockerfileFileEditor.tsx`
- `frontend/src/components/BuildModal.tsx`
- `frontend/src/components/BuildStatusBadge.tsx`
- `frontend/src/pages/DockerfilesPage.tsx`
- `frontend/tests/hooks/useDockerfiles.test.tsx`
- `frontend/tests/components/BuildStatusBadge.test.tsx`
- `frontend/tests/pages/DockerfilesPage.test.tsx`

### Frontend — files modified
- `frontend/src/App.tsx` — `/dockerfiles` route
- `frontend/src/pages/HomePage.tsx` — nav link
- `frontend/src/i18n/fr.json` + `en.json` — dockerfiles section

---

## Data model

### `dockerfiles` table (migration `007_dockerfiles.sql`)

```sql
CREATE TABLE IF NOT EXISTS dockerfiles (
    id              TEXT PRIMARY KEY,
    display_name    TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    parameters      JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_dockerfiles_display_name ON dockerfiles(display_name);
```

`id` is a slug (ex: `claude-code`, `aider`). `parameters` stores the default env/template vars declared by the dockerfile (ex: `{"ANTHROPIC_API_KEY": null, "WORKSPACE_PATH": "/app"}`) — their values come from Module 0 (Secrets) and are resolved in M4.

### `dockerfile_files` table (migration `008_dockerfile_files.sql`)

```sql
CREATE TABLE IF NOT EXISTS dockerfile_files (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    dockerfile_id   TEXT NOT NULL REFERENCES dockerfiles(id) ON DELETE CASCADE,
    path            TEXT NOT NULL,
    content         TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (dockerfile_id, path)
);

CREATE INDEX IF NOT EXISTS idx_dockerfile_files_dockerfile ON dockerfile_files(dockerfile_id);
```

`path` is a simple filename (`Dockerfile`, `entrypoint.sh`, `run.cmd.md`, `requirements.txt`, etc.). Flat structure — no directory nesting in Phase 3.

### `dockerfile_builds` table (migration `009_dockerfile_builds.sql`)

```sql
CREATE TABLE IF NOT EXISTS dockerfile_builds (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    dockerfile_id   TEXT NOT NULL REFERENCES dockerfiles(id) ON DELETE CASCADE,
    content_hash    TEXT NOT NULL,
    image_tag       TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'running', 'success', 'failed')),
    logs            TEXT NOT NULL DEFAULT '',
    started_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at     TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS idx_dockerfile_builds_dockerfile
    ON dockerfile_builds(dockerfile_id, started_at DESC);
```

One row per build attempt. `content_hash` is the deterministic hash used as image tag suffix. `logs` accumulates stdout/stderr from `aiodocker.images.build`.

### API shape

| Endpoint | Method | Body / Params | Returns |
|---|---|---|---|
| `/api/admin/dockerfiles` | GET | — | `list[DockerfileSummary]` (includes build status) |
| `/api/admin/dockerfiles` | POST | `DockerfileCreate` | `DockerfileSummary` (201) |
| `/api/admin/dockerfiles/{id}` | GET | — | `DockerfileDetail` (with files) |
| `/api/admin/dockerfiles/{id}` | PUT | `DockerfileUpdate` | `DockerfileSummary` |
| `/api/admin/dockerfiles/{id}` | DELETE | — | 204 |
| `/api/admin/dockerfiles/{id}/files` | POST | `FileCreate` | `FileSummary` (201) |
| `/api/admin/dockerfiles/{id}/files/{file_id}` | PUT | `FileUpdate` | `FileSummary` |
| `/api/admin/dockerfiles/{id}/files/{file_id}` | DELETE | — | 204 |
| `/api/admin/dockerfiles/{id}/build` | POST | — | `BuildSummary` (202 accepted) |
| `/api/admin/dockerfiles/{id}/builds` | GET | — | `list[BuildSummary]` |
| `/api/admin/dockerfiles/{id}/builds/{build_id}` | GET | — | `BuildSummary` (with logs) |

All endpoints require `Depends(require_admin)`.

**Build status computation** (for the sidebar badge):
- Compute `current_hash` from files
- Look up latest build for this dockerfile
- If no build → **🔴 never built**
- If latest build's `content_hash == current_hash` and `status == 'success'` → **🟢 up to date**
- If latest `status == 'failed'` → **🔴 failed**
- If latest `content_hash != current_hash` → **🟠 outdated**
- If latest `status in ('pending', 'running')` → **🔵 building**

### Hash algorithm

```python
def compute_hash(files: list[FileContent]) -> str:
    """SHA256 of Dockerfile + all *.sh files sorted alphabetically."""
    relevant = sorted(
        (f for f in files if f.path == "Dockerfile" or f.path.endswith(".sh")),
        key=lambda f: f.path,
    )
    h = hashlib.sha256()
    for f in relevant:
        h.update(f.path.encode())
        h.update(b"\n")
        h.update(f.content.encode())
        h.update(b"\n---\n")
    return h.hexdigest()[:12]  # short hash for image tag
```

Image tag format: `agflow-{dockerfile_id}:{hash}` (ex: `agflow-claude-code:a1b2c3d4e5f6`).

---

## Tasks

### Task 1: Migrations 007 + 008 + 009

**Files:**
- Create: `backend/migrations/007_dockerfiles.sql`
- Create: `backend/migrations/008_dockerfile_files.sql`
- Create: `backend/migrations/009_dockerfile_builds.sql`
- Modify: `backend/tests/test_migrations.py` (add test)

- [ ] **Step 1: Write `007_dockerfiles.sql`**

Create `backend/migrations/007_dockerfiles.sql` with the SQL from "Data model" above.

- [ ] **Step 2: Write `008_dockerfile_files.sql`**

Create `backend/migrations/008_dockerfile_files.sql` with the SQL from "Data model".

- [ ] **Step 3: Write `009_dockerfile_builds.sql`**

Create `backend/migrations/009_dockerfile_builds.sql` with the SQL from "Data model".

- [ ] **Step 4: Add migration test**

Edit `backend/tests/test_migrations.py`, append:

```python
@pytest.mark.asyncio
async def test_migrations_007_008_009_create_dockerfiles_tables() -> None:
    await execute("DROP TABLE IF EXISTS dockerfile_builds CASCADE")
    await execute("DROP TABLE IF EXISTS dockerfile_files CASCADE")
    await execute("DROP TABLE IF EXISTS dockerfiles CASCADE")
    await execute("DROP TABLE IF EXISTS role_documents CASCADE")
    await execute("DROP TABLE IF EXISTS roles CASCADE")
    await execute("DROP TABLE IF EXISTS secrets CASCADE")
    await execute("DROP TABLE IF EXISTS schema_migrations CASCADE")

    applied = await run_migrations(_MIGRATIONS_DIR)

    assert "007_dockerfiles" in applied
    assert "008_dockerfile_files" in applied
    assert "009_dockerfile_builds" in applied

    rows = await fetch_all(
        """
        SELECT table_name FROM information_schema.tables
        WHERE table_name IN ('dockerfiles', 'dockerfile_files', 'dockerfile_builds')
        ORDER BY table_name
        """
    )
    names = [r["table_name"] for r in rows]
    assert set(names) == {"dockerfile_builds", "dockerfile_files", "dockerfiles"}
    await close_pool()
```

- [ ] **Step 5: Run migration tests**

Run: `cd backend && uv run python -m pytest tests/test_migrations.py -v`
Expected: 5 passed (4 previous + 1 new).

- [ ] **Step 6: Commit**

```bash
git add backend/migrations/007_*.sql backend/migrations/008_*.sql backend/migrations/009_*.sql backend/tests/test_migrations.py
git commit -m "feat(m1): migrations 007_dockerfiles + 008_dockerfile_files + 009_dockerfile_builds"
```

---

### Task 2: Pydantic schemas

**Files:**
- Create: `backend/src/agflow/schemas/dockerfiles.py`

- [ ] **Step 1: Create schemas file**

Create `backend/src/agflow/schemas/dockerfiles.py`:

```python
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

BuildStatus = Literal["pending", "running", "success", "failed"]
DisplayStatus = Literal["never_built", "up_to_date", "outdated", "failed", "building"]


class DockerfileCreate(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=200)
    description: str = ""
    parameters: dict = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def _slug(cls, v: str) -> str:
        v = v.strip().lower()
        if not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError(
                "id must be a slug: lowercase alphanumeric + _ and -"
            )
        return v


class DockerfileUpdate(BaseModel):
    display_name: str | None = None
    description: str | None = None
    parameters: dict | None = None


class DockerfileSummary(BaseModel):
    id: str
    display_name: str
    description: str
    parameters: dict
    current_hash: str
    display_status: DisplayStatus
    latest_build_id: UUID | None
    created_at: datetime
    updated_at: datetime


class FileCreate(BaseModel):
    path: str = Field(min_length=1, max_length=200)
    content: str = ""

    @field_validator("path")
    @classmethod
    def _clean_path(cls, v: str) -> str:
        v = v.strip()
        if "/" in v or "\\" in v:
            raise ValueError("path must be a flat filename (no directories)")
        if not v:
            raise ValueError("path cannot be empty")
        return v


class FileUpdate(BaseModel):
    content: str | None = None


class FileSummary(BaseModel):
    id: UUID
    dockerfile_id: str
    path: str
    content: str
    created_at: datetime
    updated_at: datetime


class DockerfileDetail(BaseModel):
    dockerfile: DockerfileSummary
    files: list[FileSummary]


class BuildSummary(BaseModel):
    id: UUID
    dockerfile_id: str
    content_hash: str
    image_tag: str
    status: BuildStatus
    logs: str
    started_at: datetime
    finished_at: datetime | None
```

- [ ] **Step 2: Smoke test schemas**

Run:
```bash
cd backend && uv run python -c "
from agflow.schemas.dockerfiles import DockerfileCreate, FileCreate
d = DockerfileCreate(id='Claude-Code', display_name='Claude Code')
print('dockerfile id:', d.id)
f = FileCreate(path='Dockerfile', content='FROM alpine')
print('file path:', f.path)
try:
    FileCreate(path='sub/file.sh', content='')
except ValueError as e:
    print('slash rejected:', e)
"
```
Expected: dockerfile id lowered + slash rejection works.

- [ ] **Step 3: Commit**

```bash
git add backend/src/agflow/schemas/dockerfiles.py
git commit -m "feat(m1): Pydantic schemas for dockerfiles + files + builds"
```

---

### Task 3: `build_service.py` with hash + aiodocker wrapper (TDD for hash)

**Files:**
- Create: `backend/src/agflow/services/build_service.py`
- Create: `backend/tests/test_build_service.py`

**Scope of this task** : only the *pure* parts (hash computation, image tag format). The aiodocker build itself is integration-level and will be exercised in Task 6 (endpoint test) and Task 13 (manual smoke).

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_build_service.py`:

```python
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost/test")
os.environ.setdefault("JWT_SECRET", "x")
os.environ.setdefault("ADMIN_EMAIL", "a@b.c")
os.environ.setdefault("ADMIN_PASSWORD_HASH", "x")
os.environ.setdefault("SECRETS_MASTER_KEY", "x")

from agflow.services.build_service import compute_hash, image_tag_for  # noqa: E402


def _file(path: str, content: str) -> dict:
    return {"path": path, "content": content}


def test_compute_hash_is_deterministic() -> None:
    files = [
        _file("Dockerfile", "FROM alpine"),
        _file("entrypoint.sh", "#!/bin/sh\necho hi"),
    ]
    h1 = compute_hash(files)
    h2 = compute_hash(list(reversed(files)))
    assert h1 == h2
    assert len(h1) == 12


def test_compute_hash_ignores_non_dockerfile_non_sh() -> None:
    files = [
        _file("Dockerfile", "FROM alpine"),
        _file("README.md", "anything"),
    ]
    files_with_readme = files + [_file("README.md", "different content")]
    assert compute_hash(files) == compute_hash(files_with_readme)


def test_compute_hash_changes_when_dockerfile_changes() -> None:
    files_a = [_file("Dockerfile", "FROM alpine:3.18")]
    files_b = [_file("Dockerfile", "FROM alpine:3.19")]
    assert compute_hash(files_a) != compute_hash(files_b)


def test_compute_hash_includes_all_sh_files() -> None:
    files_a = [
        _file("Dockerfile", "FROM alpine"),
        _file("a.sh", "echo A"),
        _file("b.sh", "echo B"),
    ]
    files_b = [
        _file("Dockerfile", "FROM alpine"),
        _file("a.sh", "echo A"),
        _file("b.sh", "echo B_CHANGED"),
    ]
    assert compute_hash(files_a) != compute_hash(files_b)


def test_image_tag_format() -> None:
    assert image_tag_for("claude-code", "a1b2c3d4e5f6") == "agflow-claude-code:a1b2c3d4e5f6"
```

- [ ] **Step 2: Run — expect module not found**

Run: `cd backend && uv run python -m pytest tests/test_build_service.py -v`

- [ ] **Step 3: Implement `build_service.py`**

Create `backend/src/agflow/services/build_service.py`:

```python
from __future__ import annotations

import hashlib
import io
import tarfile
from dataclasses import dataclass
from typing import Any, Iterable
from uuid import UUID

import aiodocker
import structlog

from agflow.db.pool import execute, fetch_all, fetch_one, get_pool

_log = structlog.get_logger(__name__)


@dataclass
class FileDTO:
    path: str
    content: str


def compute_hash(files: Iterable[dict | FileDTO]) -> str:
    """SHA256 of Dockerfile + all *.sh files sorted alphabetically.

    Returns the first 12 hex chars, suitable for use as an image tag.
    """
    normalized: list[FileDTO] = []
    for f in files:
        if isinstance(f, FileDTO):
            normalized.append(f)
        else:
            normalized.append(FileDTO(path=f["path"], content=f["content"]))

    relevant = sorted(
        (f for f in normalized if f.path == "Dockerfile" or f.path.endswith(".sh")),
        key=lambda f: f.path,
    )
    h = hashlib.sha256()
    for f in relevant:
        h.update(f.path.encode())
        h.update(b"\n")
        h.update(f.content.encode())
        h.update(b"\n---\n")
    return h.hexdigest()[:12]


def image_tag_for(dockerfile_id: str, content_hash: str) -> str:
    return f"agflow-{dockerfile_id}:{content_hash}"


def _build_tar_context(files: list[FileDTO]) -> bytes:
    """Create an in-memory tar archive containing all files at the tar root."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for f in files:
            data = f.content.encode()
            info = tarfile.TarInfo(name=f.path)
            info.size = len(data)
            info.mode = 0o755 if f.path.endswith(".sh") else 0o644
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


async def _append_log(build_id: UUID, chunk: str) -> None:
    await execute(
        "UPDATE dockerfile_builds SET logs = logs || $2 WHERE id = $1",
        build_id,
        chunk,
    )


async def _set_status(
    build_id: UUID, status: str, finished: bool = False
) -> None:
    if finished:
        await execute(
            "UPDATE dockerfile_builds SET status = $2, finished_at = NOW() WHERE id = $1",
            build_id,
            status,
        )
    else:
        await execute(
            "UPDATE dockerfile_builds SET status = $2 WHERE id = $1",
            build_id,
            status,
        )


async def run_build(build_id: UUID, dockerfile_id: str, tag: str) -> None:
    """Run a docker build for a previously-recorded build row.

    Streams logs into the `logs` column. Flips `status` at the end.
    """
    rows = await fetch_all(
        "SELECT path, content FROM dockerfile_files WHERE dockerfile_id = $1",
        dockerfile_id,
    )
    files = [FileDTO(path=r["path"], content=r["content"]) for r in rows]

    has_dockerfile = any(f.path == "Dockerfile" for f in files)
    if not has_dockerfile:
        await _append_log(
            build_id, "ERROR: no file named 'Dockerfile' in this dockerfile\n"
        )
        await _set_status(build_id, "failed", finished=True)
        return

    context = _build_tar_context(files)

    await _set_status(build_id, "running")
    _log.info("build.start", dockerfile_id=dockerfile_id, tag=tag, build_id=str(build_id))

    try:
        docker = aiodocker.Docker()
        try:
            async for chunk in docker.images.build(
                fileobj=io.BytesIO(context),
                encoding="identity",
                tag=tag,
                stream=True,
            ):
                line = _format_chunk(chunk)
                if line:
                    await _append_log(build_id, line + "\n")
        finally:
            await docker.close()
    except Exception as exc:
        _log.exception("build.error", build_id=str(build_id))
        await _append_log(build_id, f"\nBUILD ERROR: {exc}\n")
        await _set_status(build_id, "failed", finished=True)
        return

    await _set_status(build_id, "success", finished=True)
    _log.info("build.done", build_id=str(build_id))


def _format_chunk(chunk: Any) -> str:
    if isinstance(chunk, dict):
        if "stream" in chunk:
            return chunk["stream"].rstrip("\n")
        if "error" in chunk:
            return f"ERROR: {chunk['error']}"
        if "status" in chunk:
            return chunk["status"]
    return str(chunk).rstrip("\n")


async def create_build_row(
    dockerfile_id: str, content_hash: str, tag: str
) -> UUID:
    row = await fetch_one(
        """
        INSERT INTO dockerfile_builds (dockerfile_id, content_hash, image_tag)
        VALUES ($1, $2, $3)
        RETURNING id
        """,
        dockerfile_id,
        content_hash,
        tag,
    )
    assert row is not None
    return row["id"]


async def get_latest_build(dockerfile_id: str) -> dict | None:
    return await fetch_one(
        """
        SELECT id, content_hash, status FROM dockerfile_builds
        WHERE dockerfile_id = $1
        ORDER BY started_at DESC
        LIMIT 1
        """,
        dockerfile_id,
    )


async def list_builds(dockerfile_id: str) -> list[dict]:
    return await fetch_all(
        """
        SELECT id, dockerfile_id, content_hash, image_tag, status, logs,
               started_at, finished_at
        FROM dockerfile_builds
        WHERE dockerfile_id = $1
        ORDER BY started_at DESC
        """,
        dockerfile_id,
    )


async def get_build(build_id: UUID) -> dict | None:
    return await fetch_one(
        """
        SELECT id, dockerfile_id, content_hash, image_tag, status, logs,
               started_at, finished_at
        FROM dockerfile_builds
        WHERE id = $1
        """,
        build_id,
    )
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run python -m pytest tests/test_build_service.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/agflow/services/build_service.py backend/tests/test_build_service.py
git commit -m "feat(m1): build_service with deterministic hash + aiodocker wrapper"
```

---

### Task 4: `dockerfiles_service.py` CRUD (TDD)

**Files:**
- Create: `backend/src/agflow/services/dockerfiles_service.py`
- Create: `backend/tests/test_dockerfiles_service.py`

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_dockerfiles_service.py`:

```python
from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ["DATABASE_URL"] = "postgresql://agflow:agflow_dev@192.168.10.82:5432/agflow"
os.environ.setdefault("SECRETS_MASTER_KEY", "test-master-key-phrase-32chars-ok")

from agflow.db.migrations import run_migrations  # noqa: E402
from agflow.db.pool import close_pool, execute  # noqa: E402
from agflow.services import dockerfiles_service  # noqa: E402

_MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


@pytest.fixture(autouse=True)
async def _clean():
    await execute("DROP TABLE IF EXISTS dockerfile_builds CASCADE")
    await execute("DROP TABLE IF EXISTS dockerfile_files CASCADE")
    await execute("DROP TABLE IF EXISTS dockerfiles CASCADE")
    await execute("DROP TABLE IF EXISTS role_documents CASCADE")
    await execute("DROP TABLE IF EXISTS roles CASCADE")
    await execute("DROP TABLE IF EXISTS secrets CASCADE")
    await execute("DROP TABLE IF EXISTS schema_migrations CASCADE")
    await run_migrations(_MIGRATIONS_DIR)
    yield
    await close_pool()


@pytest.mark.asyncio
async def test_create_and_get() -> None:
    summary = await dockerfiles_service.create(
        dockerfile_id="claude-code",
        display_name="Claude Code",
        description="CLI agent claude-code",
        parameters={"ANTHROPIC_API_KEY": None},
    )
    assert summary.id == "claude-code"
    assert summary.display_name == "Claude Code"
    assert summary.parameters == {"ANTHROPIC_API_KEY": None}
    assert summary.display_status == "never_built"

    again = await dockerfiles_service.get_by_id("claude-code")
    assert again.id == "claude-code"


@pytest.mark.asyncio
async def test_duplicate_raises() -> None:
    await dockerfiles_service.create(dockerfile_id="dup", display_name="D")
    with pytest.raises(dockerfiles_service.DuplicateDockerfileError):
        await dockerfiles_service.create(dockerfile_id="dup", display_name="D2")


@pytest.mark.asyncio
async def test_list_all() -> None:
    await dockerfiles_service.create(dockerfile_id="b", display_name="B")
    await dockerfiles_service.create(dockerfile_id="a", display_name="A")

    items = await dockerfiles_service.list_all()
    assert [i.id for i in items] == ["a", "b"]


@pytest.mark.asyncio
async def test_update() -> None:
    await dockerfiles_service.create(dockerfile_id="upd", display_name="Old")

    updated = await dockerfiles_service.update(
        "upd", display_name="New", description="desc"
    )
    assert updated.display_name == "New"
    assert updated.description == "desc"


@pytest.mark.asyncio
async def test_delete() -> None:
    await dockerfiles_service.create(dockerfile_id="del", display_name="Del")
    await dockerfiles_service.delete("del")

    with pytest.raises(dockerfiles_service.DockerfileNotFoundError):
        await dockerfiles_service.get_by_id("del")
```

- [ ] **Step 2: Run — expect module not found**

Run: `cd backend && uv run python -m pytest tests/test_dockerfiles_service.py -v`

- [ ] **Step 3: Implement `dockerfiles_service.py`**

Create `backend/src/agflow/services/dockerfiles_service.py`:

```python
from __future__ import annotations

import json
from typing import Any

import asyncpg
import structlog

from agflow.db.pool import fetch_all, fetch_one, get_pool
from agflow.schemas.dockerfiles import DisplayStatus, DockerfileSummary
from agflow.services import build_service
from agflow.services import dockerfile_files_service

_log = structlog.get_logger(__name__)


class DockerfileNotFoundError(Exception):
    pass


class DuplicateDockerfileError(Exception):
    pass


def _parse_params(raw: Any) -> dict:
    if isinstance(raw, str):
        return json.loads(raw) if raw else {}
    return raw or {}


async def _compute_display_status(
    dockerfile_id: str,
) -> tuple[str, DisplayStatus, str | None]:
    """Return (current_hash, display_status, latest_build_id)."""
    files = await dockerfile_files_service.list_for_dockerfile(dockerfile_id)
    current_hash = build_service.compute_hash(
        [{"path": f.path, "content": f.content} for f in files]
    )
    latest = await build_service.get_latest_build(dockerfile_id)
    if latest is None:
        return current_hash, "never_built", None

    latest_id = str(latest["id"])
    if latest["status"] == "failed":
        return current_hash, "failed", latest_id
    if latest["status"] in ("pending", "running"):
        return current_hash, "building", latest_id
    if latest["content_hash"] == current_hash and latest["status"] == "success":
        return current_hash, "up_to_date", latest_id
    return current_hash, "outdated", latest_id


async def _row_to_summary(row: dict[str, Any]) -> DockerfileSummary:
    current_hash, display_status, latest_id = await _compute_display_status(row["id"])
    return DockerfileSummary(
        id=row["id"],
        display_name=row["display_name"],
        description=row["description"],
        parameters=_parse_params(row["parameters"]),
        current_hash=current_hash,
        display_status=display_status,
        latest_build_id=latest_id,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def create(
    dockerfile_id: str,
    display_name: str,
    description: str = "",
    parameters: dict | None = None,
) -> DockerfileSummary:
    try:
        row = await fetch_one(
            """
            INSERT INTO dockerfiles (id, display_name, description, parameters)
            VALUES ($1, $2, $3, $4::jsonb)
            RETURNING id, display_name, description, parameters,
                      created_at, updated_at
            """,
            dockerfile_id,
            display_name,
            description,
            json.dumps(parameters or {}),
        )
    except asyncpg.UniqueViolationError as exc:
        raise DuplicateDockerfileError(
            f"Dockerfile '{dockerfile_id}' already exists"
        ) from exc
    assert row is not None
    _log.info("dockerfiles.create", dockerfile_id=dockerfile_id)
    return await _row_to_summary(row)


async def list_all() -> list[DockerfileSummary]:
    rows = await fetch_all(
        """
        SELECT id, display_name, description, parameters, created_at, updated_at
        FROM dockerfiles
        ORDER BY id ASC
        """
    )
    return [await _row_to_summary(r) for r in rows]


async def get_by_id(dockerfile_id: str) -> DockerfileSummary:
    row = await fetch_one(
        """
        SELECT id, display_name, description, parameters, created_at, updated_at
        FROM dockerfiles
        WHERE id = $1
        """,
        dockerfile_id,
    )
    if row is None:
        raise DockerfileNotFoundError(f"Dockerfile '{dockerfile_id}' not found")
    return await _row_to_summary(row)


async def update(
    dockerfile_id: str,
    display_name: str | None = None,
    description: str | None = None,
    parameters: dict | None = None,
) -> DockerfileSummary:
    sets: list[str] = []
    args: list[Any] = []
    idx = 1
    if display_name is not None:
        sets.append(f"display_name = ${idx}")
        args.append(display_name)
        idx += 1
    if description is not None:
        sets.append(f"description = ${idx}")
        args.append(description)
        idx += 1
    if parameters is not None:
        sets.append(f"parameters = ${idx}::jsonb")
        args.append(json.dumps(parameters))
        idx += 1
    if not sets:
        return await get_by_id(dockerfile_id)
    sets.append("updated_at = NOW()")
    args.append(dockerfile_id)

    row = await fetch_one(
        f"""
        UPDATE dockerfiles SET {", ".join(sets)}
        WHERE id = ${idx}
        RETURNING id, display_name, description, parameters, created_at, updated_at
        """,
        *args,
    )
    if row is None:
        raise DockerfileNotFoundError(f"Dockerfile '{dockerfile_id}' not found")
    _log.info("dockerfiles.update", dockerfile_id=dockerfile_id)
    return await _row_to_summary(row)


async def delete(dockerfile_id: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM dockerfiles WHERE id = $1", dockerfile_id)
    if result == "DELETE 0":
        raise DockerfileNotFoundError(f"Dockerfile '{dockerfile_id}' not found")
    _log.info("dockerfiles.delete", dockerfile_id=dockerfile_id)
```

- [ ] **Step 4: Run — expect dockerfile_files_service not found**

Run: `cd backend && uv run python -m pytest tests/test_dockerfiles_service.py -v`
Expected: import error on `dockerfile_files_service` (which we create in Task 5).

- [ ] **Step 5: Stub out `dockerfile_files_service` temporarily**

Create a minimal stub `backend/src/agflow/services/dockerfile_files_service.py`:

```python
from __future__ import annotations

from agflow.schemas.dockerfiles import FileSummary


async def list_for_dockerfile(dockerfile_id: str) -> list[FileSummary]:
    return []
```

- [ ] **Step 6: Run tests**

Run: `cd backend && uv run python -m pytest tests/test_dockerfiles_service.py -v`
Expected: 5 passed.

- [ ] **Step 7: Commit**

```bash
git add backend/src/agflow/services/dockerfiles_service.py backend/src/agflow/services/dockerfile_files_service.py backend/tests/test_dockerfiles_service.py
git commit -m "feat(m1): dockerfiles_service CRUD + display_status computation"
```

---

### Task 5: `dockerfile_files_service.py` full implementation (TDD)

**Files:**
- Modify: `backend/src/agflow/services/dockerfile_files_service.py` (replace stub)
- Create: `backend/tests/test_dockerfile_files_service.py`

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_dockerfile_files_service.py`:

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
from agflow.services import dockerfile_files_service as files  # noqa: E402
from agflow.services import dockerfiles_service  # noqa: E402

_MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


@pytest.fixture(autouse=True)
async def _clean():
    await execute("DROP TABLE IF EXISTS dockerfile_builds CASCADE")
    await execute("DROP TABLE IF EXISTS dockerfile_files CASCADE")
    await execute("DROP TABLE IF EXISTS dockerfiles CASCADE")
    await execute("DROP TABLE IF EXISTS role_documents CASCADE")
    await execute("DROP TABLE IF EXISTS roles CASCADE")
    await execute("DROP TABLE IF EXISTS secrets CASCADE")
    await execute("DROP TABLE IF EXISTS schema_migrations CASCADE")
    await run_migrations(_MIGRATIONS_DIR)
    await dockerfiles_service.create(dockerfile_id="test", display_name="Test")
    yield
    await close_pool()


@pytest.mark.asyncio
async def test_create_file() -> None:
    f = await files.create(
        dockerfile_id="test",
        path="Dockerfile",
        content="FROM alpine",
    )
    assert f.dockerfile_id == "test"
    assert f.path == "Dockerfile"
    assert f.content == "FROM alpine"


@pytest.mark.asyncio
async def test_duplicate_path_raises() -> None:
    await files.create(dockerfile_id="test", path="Dockerfile", content="")
    with pytest.raises(files.DuplicateFileError):
        await files.create(dockerfile_id="test", path="Dockerfile", content="x")


@pytest.mark.asyncio
async def test_list_for_dockerfile() -> None:
    await files.create(dockerfile_id="test", path="Dockerfile", content="")
    await files.create(dockerfile_id="test", path="entrypoint.sh", content="")
    await files.create(dockerfile_id="test", path="run.cmd.md", content="")

    items = await files.list_for_dockerfile("test")
    paths = [i.path for i in items]
    assert set(paths) == {"Dockerfile", "entrypoint.sh", "run.cmd.md"}


@pytest.mark.asyncio
async def test_update_content() -> None:
    f = await files.create(dockerfile_id="test", path="a.sh", content="old")
    updated = await files.update(f.id, content="new")
    assert updated.content == "new"


@pytest.mark.asyncio
async def test_delete_file() -> None:
    f = await files.create(dockerfile_id="test", path="x", content="")
    await files.delete(f.id)

    remaining = await files.list_for_dockerfile("test")
    assert all(fx.id != f.id for fx in remaining)


@pytest.mark.asyncio
async def test_get_by_id_missing() -> None:
    with pytest.raises(files.FileNotFoundError):
        await files.get_by_id(uuid.uuid4())
```

- [ ] **Step 2: Run — expect failures**

Run: `cd backend && uv run python -m pytest tests/test_dockerfile_files_service.py -v`
Expected: `DuplicateFileError` and `FileNotFoundError` don't exist yet, `create` returns empty, etc.

- [ ] **Step 3: Implement full `dockerfile_files_service.py`**

Overwrite `backend/src/agflow/services/dockerfile_files_service.py`:

```python
from __future__ import annotations

from uuid import UUID

import asyncpg
import structlog

from agflow.db.pool import fetch_all, fetch_one, get_pool
from agflow.schemas.dockerfiles import FileSummary

_log = structlog.get_logger(__name__)

_FILE_COLS = (
    "id, dockerfile_id, path, content, created_at, updated_at"
)


class FileNotFoundError(Exception):
    pass


class DuplicateFileError(Exception):
    pass


def _row(row: dict) -> FileSummary:
    return FileSummary(**row)


async def create(
    dockerfile_id: str,
    path: str,
    content: str = "",
) -> FileSummary:
    try:
        row = await fetch_one(
            f"""
            INSERT INTO dockerfile_files (dockerfile_id, path, content)
            VALUES ($1, $2, $3)
            RETURNING {_FILE_COLS}
            """,
            dockerfile_id,
            path,
            content,
        )
    except asyncpg.UniqueViolationError as exc:
        raise DuplicateFileError(
            f"File '{path}' already exists in dockerfile '{dockerfile_id}'"
        ) from exc
    assert row is not None
    _log.info("dockerfile_files.create", dockerfile_id=dockerfile_id, path=path)
    return _row(row)


async def get_by_id(file_id: UUID) -> FileSummary:
    row = await fetch_one(
        f"SELECT {_FILE_COLS} FROM dockerfile_files WHERE id = $1", file_id
    )
    if row is None:
        raise FileNotFoundError(f"File {file_id} not found")
    return _row(row)


async def list_for_dockerfile(dockerfile_id: str) -> list[FileSummary]:
    rows = await fetch_all(
        f"""
        SELECT {_FILE_COLS} FROM dockerfile_files
        WHERE dockerfile_id = $1
        ORDER BY path ASC
        """,
        dockerfile_id,
    )
    return [_row(r) for r in rows]


async def update(file_id: UUID, content: str | None = None) -> FileSummary:
    if content is None:
        return await get_by_id(file_id)
    row = await fetch_one(
        f"""
        UPDATE dockerfile_files
        SET content = $2, updated_at = NOW()
        WHERE id = $1
        RETURNING {_FILE_COLS}
        """,
        file_id,
        content,
    )
    if row is None:
        raise FileNotFoundError(f"File {file_id} not found")
    _log.info("dockerfile_files.update", file_id=str(file_id))
    return _row(row)


async def delete(file_id: UUID) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM dockerfile_files WHERE id = $1", file_id
        )
    if result == "DELETE 0":
        raise FileNotFoundError(f"File {file_id} not found")
    _log.info("dockerfile_files.delete", file_id=str(file_id))
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run python -m pytest tests/test_dockerfile_files_service.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/src/agflow/services/dockerfile_files_service.py backend/tests/test_dockerfile_files_service.py
git commit -m "feat(m1): dockerfile_files_service CRUD + 6 tests"
```

---

### Task 6: Admin router + endpoint tests

**Files:**
- Create: `backend/src/agflow/api/admin/dockerfiles.py`
- Create: `backend/tests/test_dockerfiles_endpoint.py`
- Modify: `backend/src/agflow/main.py`

- [ ] **Step 1: Write failing endpoint tests**

Create `backend/tests/test_dockerfiles_endpoint.py`:

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

_MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    await execute("DROP TABLE IF EXISTS dockerfile_builds CASCADE")
    await execute("DROP TABLE IF EXISTS dockerfile_files CASCADE")
    await execute("DROP TABLE IF EXISTS dockerfiles CASCADE")
    await execute("DROP TABLE IF EXISTS role_documents CASCADE")
    await execute("DROP TABLE IF EXISTS roles CASCADE")
    await execute("DROP TABLE IF EXISTS secrets CASCADE")
    await execute("DROP TABLE IF EXISTS schema_migrations CASCADE")
    await run_migrations(_MIGRATIONS_DIR)

    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c

    await close_pool()


async def _token(c: AsyncClient) -> dict[str, str]:
    res = await c.post(
        "/api/admin/auth/login",
        json={"email": "admin@example.com", "password": "correct-password"},
    )
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.mark.asyncio
async def test_create_dockerfile_and_list(client: AsyncClient) -> None:
    headers = await _token(client)

    create = await client.post(
        "/api/admin/dockerfiles",
        headers=headers,
        json={"id": "claude-code", "display_name": "Claude Code"},
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["id"] == "claude-code"
    assert body["display_status"] == "never_built"

    listing = await client.get("/api/admin/dockerfiles", headers=headers)
    assert listing.status_code == 200
    assert any(d["id"] == "claude-code" for d in listing.json())


@pytest.mark.asyncio
async def test_file_crud(client: AsyncClient) -> None:
    headers = await _token(client)

    await client.post(
        "/api/admin/dockerfiles",
        headers=headers,
        json={"id": "df", "display_name": "DF"},
    )

    create_file = await client.post(
        "/api/admin/dockerfiles/df/files",
        headers=headers,
        json={"path": "Dockerfile", "content": "FROM alpine"},
    )
    assert create_file.status_code == 201
    file_id = create_file.json()["id"]

    detail = await client.get("/api/admin/dockerfiles/df", headers=headers)
    assert detail.status_code == 200
    assert len(detail.json()["files"]) == 1

    update_file = await client.put(
        f"/api/admin/dockerfiles/df/files/{file_id}",
        headers=headers,
        json={"content": "FROM alpine:3.19"},
    )
    assert update_file.status_code == 200
    assert update_file.json()["content"] == "FROM alpine:3.19"

    delete_file = await client.delete(
        f"/api/admin/dockerfiles/df/files/{file_id}", headers=headers
    )
    assert delete_file.status_code == 204


@pytest.mark.asyncio
async def test_build_endpoint_mocked(client: AsyncClient) -> None:
    headers = await _token(client)

    await client.post(
        "/api/admin/dockerfiles",
        headers=headers,
        json={"id": "mdf", "display_name": "MockDF"},
    )
    await client.post(
        "/api/admin/dockerfiles/mdf/files",
        headers=headers,
        json={"path": "Dockerfile", "content": "FROM alpine"},
    )

    with patch(
        "agflow.api.admin.dockerfiles.build_service.run_build",
        new=AsyncMock(return_value=None),
    ):
        res = await client.post(
            "/api/admin/dockerfiles/mdf/build", headers=headers
        )

    assert res.status_code == 202
    body = res.json()
    assert body["dockerfile_id"] == "mdf"
    assert body["status"] == "pending"
    assert body["image_tag"].startswith("agflow-mdf:")


@pytest.mark.asyncio
async def test_list_builds(client: AsyncClient) -> None:
    headers = await _token(client)

    await client.post(
        "/api/admin/dockerfiles",
        headers=headers,
        json={"id": "lb", "display_name": "LB"},
    )
    await client.post(
        "/api/admin/dockerfiles/lb/files",
        headers=headers,
        json={"path": "Dockerfile", "content": "FROM alpine"},
    )

    with patch(
        "agflow.api.admin.dockerfiles.build_service.run_build",
        new=AsyncMock(return_value=None),
    ):
        await client.post("/api/admin/dockerfiles/lb/build", headers=headers)

    res = await client.get("/api/admin/dockerfiles/lb/builds", headers=headers)
    assert res.status_code == 200
    assert len(res.json()) >= 1


@pytest.mark.asyncio
async def test_delete_dockerfile_cascades_files(client: AsyncClient) -> None:
    headers = await _token(client)

    await client.post(
        "/api/admin/dockerfiles",
        headers=headers,
        json={"id": "cas", "display_name": "Cas"},
    )
    await client.post(
        "/api/admin/dockerfiles/cas/files",
        headers=headers,
        json={"path": "Dockerfile", "content": ""},
    )

    delres = await client.delete("/api/admin/dockerfiles/cas", headers=headers)
    assert delres.status_code == 204

    listing = await client.get("/api/admin/dockerfiles", headers=headers)
    assert all(d["id"] != "cas" for d in listing.json())
```

- [ ] **Step 2: Run — expect 404**

Run: `cd backend && uv run python -m pytest tests/test_dockerfiles_endpoint.py -v`

- [ ] **Step 3: Implement the router**

Create `backend/src/agflow/api/admin/dockerfiles.py`:

```python
from __future__ import annotations

import asyncio
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status

from agflow.auth.dependencies import require_admin
from agflow.schemas.dockerfiles import (
    BuildSummary,
    DockerfileCreate,
    DockerfileDetail,
    DockerfileSummary,
    DockerfileUpdate,
    FileCreate,
    FileSummary,
    FileUpdate,
)
from agflow.services import (
    build_service,
    dockerfile_files_service,
    dockerfiles_service,
)

router = APIRouter(
    prefix="/api/admin/dockerfiles",
    tags=["admin-dockerfiles"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[DockerfileSummary])
async def list_dockerfiles() -> list[DockerfileSummary]:
    return await dockerfiles_service.list_all()


@router.post(
    "", response_model=DockerfileSummary, status_code=status.HTTP_201_CREATED
)
async def create_dockerfile(payload: DockerfileCreate) -> DockerfileSummary:
    try:
        return await dockerfiles_service.create(
            dockerfile_id=payload.id,
            display_name=payload.display_name,
            description=payload.description,
            parameters=payload.parameters,
        )
    except dockerfiles_service.DuplicateDockerfileError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc


@router.get("/{dockerfile_id}", response_model=DockerfileDetail)
async def get_dockerfile(dockerfile_id: str) -> DockerfileDetail:
    try:
        dockerfile = await dockerfiles_service.get_by_id(dockerfile_id)
    except dockerfiles_service.DockerfileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    files = await dockerfile_files_service.list_for_dockerfile(dockerfile_id)
    return DockerfileDetail(dockerfile=dockerfile, files=files)


@router.put("/{dockerfile_id}", response_model=DockerfileSummary)
async def update_dockerfile(
    dockerfile_id: str, payload: DockerfileUpdate
) -> DockerfileSummary:
    try:
        return await dockerfiles_service.update(
            dockerfile_id,
            **payload.model_dump(exclude_unset=True),
        )
    except dockerfiles_service.DockerfileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.delete(
    "/{dockerfile_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_dockerfile(dockerfile_id: str) -> None:
    try:
        await dockerfiles_service.delete(dockerfile_id)
    except dockerfiles_service.DockerfileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.post(
    "/{dockerfile_id}/files",
    response_model=FileSummary,
    status_code=status.HTTP_201_CREATED,
)
async def create_file(dockerfile_id: str, payload: FileCreate) -> FileSummary:
    try:
        return await dockerfile_files_service.create(
            dockerfile_id=dockerfile_id,
            path=payload.path,
            content=payload.content,
        )
    except dockerfile_files_service.DuplicateFileError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc


@router.put(
    "/{dockerfile_id}/files/{file_id}", response_model=FileSummary
)
async def update_file(
    dockerfile_id: str, file_id: UUID, payload: FileUpdate
) -> FileSummary:
    try:
        return await dockerfile_files_service.update(
            file_id, content=payload.content
        )
    except dockerfile_files_service.FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.delete(
    "/{dockerfile_id}/files/{file_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_file(dockerfile_id: str, file_id: UUID) -> None:
    try:
        await dockerfile_files_service.delete(file_id)
    except dockerfile_files_service.FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.post(
    "/{dockerfile_id}/build",
    response_model=BuildSummary,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_build(
    dockerfile_id: str, background: BackgroundTasks
) -> BuildSummary:
    try:
        dockerfile = await dockerfiles_service.get_by_id(dockerfile_id)
    except dockerfiles_service.DockerfileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    tag = build_service.image_tag_for(dockerfile_id, dockerfile.current_hash)
    build_id = await build_service.create_build_row(
        dockerfile_id=dockerfile_id,
        content_hash=dockerfile.current_hash,
        tag=tag,
    )

    background.add_task(
        _run_build_in_background, build_id, dockerfile_id, tag
    )

    row = await build_service.get_build(build_id)
    assert row is not None
    return BuildSummary(**row)


async def _run_build_in_background(build_id: UUID, dockerfile_id: str, tag: str) -> None:
    """Wrapper to swallow exceptions from the background task."""
    try:
        await build_service.run_build(build_id, dockerfile_id, tag)
    except Exception:  # pragma: no cover
        import structlog

        structlog.get_logger(__name__).exception(
            "build.background.error", build_id=str(build_id)
        )


@router.get(
    "/{dockerfile_id}/builds", response_model=list[BuildSummary]
)
async def list_builds(dockerfile_id: str) -> list[BuildSummary]:
    rows = await build_service.list_builds(dockerfile_id)
    return [BuildSummary(**r) for r in rows]


@router.get(
    "/{dockerfile_id}/builds/{build_id}", response_model=BuildSummary
)
async def get_build(dockerfile_id: str, build_id: UUID) -> BuildSummary:
    row = await build_service.get_build(build_id)
    if row is None or row["dockerfile_id"] != dockerfile_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Build not found"
        )
    return BuildSummary(**row)
```

- [ ] **Step 4: Register in `main.py`**

Edit `backend/src/agflow/main.py`:
```python
from agflow.api.admin.dockerfiles import router as admin_dockerfiles_router
```
In `create_app()`:
```python
    app.include_router(admin_dockerfiles_router)
```

- [ ] **Step 5: Run tests**

Run: `cd backend && uv run python -m pytest tests/test_dockerfiles_endpoint.py -v`
Expected: 5 passed.

- [ ] **Step 6: Full backend suite**

Run: `cd backend && uv run python -m pytest -q`
Expected: all tests green (~60 previous + ~21 new = ~81).

- [ ] **Step 7: Commit**

```bash
git add backend/src/agflow/api/admin/dockerfiles.py backend/src/agflow/main.py backend/tests/test_dockerfiles_endpoint.py
git commit -m "feat(m1): admin dockerfiles router + 5 endpoint tests"
```

---

### Task 7: Mount docker.sock in docker-compose.prod.yml

**Files:**
- Modify: `docker-compose.prod.yml`

The backend container needs access to the host Docker daemon to launch builds via aiodocker.

- [ ] **Step 1: Add the volume mount**

Edit `docker-compose.prod.yml`, in the `backend:` service, add a `volumes:` section:

```yaml
  backend:
    image: agflow-backend:latest
    container_name: agflow-backend
    restart: unless-stopped
    env_file: .env
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    depends_on:
      postgres: { condition: service_healthy }
      redis: { condition: service_healthy }
    networks: [agflow]
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
      interval: 10s
      retries: 5
```

- [ ] **Step 2: Commit**

```bash
git add docker-compose.prod.yml
git commit -m "feat(m1): mount /var/run/docker.sock in backend for builds"
```

---

### Task 8: Frontend i18n + `dockerfilesApi.ts`

**Files:**
- Modify: `frontend/src/i18n/fr.json` + `en.json`
- Create: `frontend/src/lib/dockerfilesApi.ts`

- [ ] **Step 1: Add i18n keys (fr)**

Edit `frontend/src/i18n/fr.json`, append before the closing brace:

```json
  ,
  "dockerfiles": {
    "page_title": "Dockerfiles (runtimes des agents)",
    "page_subtitle": "Images Docker des agents CLI — une par agent",
    "add_button": "+ Ajouter un dockerfile",
    "delete_button": "Supprimer",
    "save_button": "Enregistrer",
    "build_button": "Compiler",
    "new_file_button": "+ Nouveau fichier",
    "no_dockerfiles": "Aucun dockerfile — crée ton premier",
    "select_dockerfile": "Sélectionne un dockerfile",
    "no_files": "Aucun fichier",
    "file_name_placeholder": "Ex: Dockerfile, entrypoint.sh, run.cmd.md",
    "current_hash": "Hash courant",
    "status": {
      "never_built": "🔴 Jamais compilé",
      "up_to_date": "🟢 Image à jour",
      "outdated": "🟠 Image obsolète",
      "failed": "🔴 Dernier build échoué",
      "building": "🔵 Build en cours…"
    },
    "build_modal": {
      "title": "Build en cours — {{dockerfile}}",
      "image_tag": "Image tag",
      "logs": "Logs",
      "close": "Fermer",
      "running": "Running…",
      "success": "Succès",
      "failed": "Échec"
    },
    "errors": {
      "duplicate_id": "Un dockerfile avec cet ID existe déjà",
      "duplicate_file": "Un fichier avec ce nom existe déjà",
      "generic": "Une erreur est survenue"
    },
    "new_dockerfile_id_prompt": "Identifiant du dockerfile (slug)",
    "new_dockerfile_name_prompt": "Nom d'affichage",
    "new_file_prompt": "Nom du fichier (ex: Dockerfile)",
    "confirm_delete": "Supprimer \"{{name}}\" ?"
  }
```

- [ ] **Step 2: Add i18n keys (en)** — translate the block above to English and add to `en.json`.

- [ ] **Step 3: Create `dockerfilesApi.ts`**

Create `frontend/src/lib/dockerfilesApi.ts`:

```ts
import { api } from "./api";

export type BuildStatus = "pending" | "running" | "success" | "failed";
export type DisplayStatus =
  | "never_built"
  | "up_to_date"
  | "outdated"
  | "failed"
  | "building";

export interface DockerfileSummary {
  id: string;
  display_name: string;
  description: string;
  parameters: Record<string, unknown>;
  current_hash: string;
  display_status: DisplayStatus;
  latest_build_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface FileSummary {
  id: string;
  dockerfile_id: string;
  path: string;
  content: string;
  created_at: string;
  updated_at: string;
}

export interface DockerfileDetail {
  dockerfile: DockerfileSummary;
  files: FileSummary[];
}

export interface BuildSummary {
  id: string;
  dockerfile_id: string;
  content_hash: string;
  image_tag: string;
  status: BuildStatus;
  logs: string;
  started_at: string;
  finished_at: string | null;
}

export interface DockerfileCreate {
  id: string;
  display_name: string;
  description?: string;
  parameters?: Record<string, unknown>;
}

export interface FileCreate {
  path: string;
  content?: string;
}

export const dockerfilesApi = {
  async list(): Promise<DockerfileSummary[]> {
    const res = await api.get<DockerfileSummary[]>("/admin/dockerfiles");
    return res.data;
  },
  async get(id: string): Promise<DockerfileDetail> {
    const res = await api.get<DockerfileDetail>(`/admin/dockerfiles/${id}`);
    return res.data;
  },
  async create(payload: DockerfileCreate): Promise<DockerfileSummary> {
    const res = await api.post<DockerfileSummary>("/admin/dockerfiles", payload);
    return res.data;
  },
  async remove(id: string): Promise<void> {
    await api.delete(`/admin/dockerfiles/${id}`);
  },
  async createFile(
    dockerfileId: string,
    payload: FileCreate,
  ): Promise<FileSummary> {
    const res = await api.post<FileSummary>(
      `/admin/dockerfiles/${dockerfileId}/files`,
      payload,
    );
    return res.data;
  },
  async updateFile(
    dockerfileId: string,
    fileId: string,
    content: string,
  ): Promise<FileSummary> {
    const res = await api.put<FileSummary>(
      `/admin/dockerfiles/${dockerfileId}/files/${fileId}`,
      { content },
    );
    return res.data;
  },
  async deleteFile(dockerfileId: string, fileId: string): Promise<void> {
    await api.delete(`/admin/dockerfiles/${dockerfileId}/files/${fileId}`);
  },
  async build(dockerfileId: string): Promise<BuildSummary> {
    const res = await api.post<BuildSummary>(
      `/admin/dockerfiles/${dockerfileId}/build`,
    );
    return res.data;
  },
  async getBuild(dockerfileId: string, buildId: string): Promise<BuildSummary> {
    const res = await api.get<BuildSummary>(
      `/admin/dockerfiles/${dockerfileId}/builds/${buildId}`,
    );
    return res.data;
  },
};
```

- [ ] **Step 4: TS check**

Run: `cd frontend && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/i18n/fr.json frontend/src/i18n/en.json frontend/src/lib/dockerfilesApi.ts
git commit -m "feat(m1): frontend i18n + dockerfilesApi client"
```

---

### Task 9: `useDockerfiles` + `useBuild` hooks (TDD)

**Files:**
- Create: `frontend/src/hooks/useDockerfiles.ts`
- Create: `frontend/src/hooks/useBuild.ts`
- Create: `frontend/tests/hooks/useDockerfiles.test.tsx`

- [ ] **Step 1: Write failing test**

Create `frontend/tests/hooks/useDockerfiles.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useDockerfiles } from "@/hooks/useDockerfiles";
import { dockerfilesApi } from "@/lib/dockerfilesApi";

vi.mock("@/lib/dockerfilesApi", () => ({
  dockerfilesApi: {
    list: vi.fn(),
    get: vi.fn(),
    create: vi.fn(),
    remove: vi.fn(),
    createFile: vi.fn(),
    updateFile: vi.fn(),
    deleteFile: vi.fn(),
    build: vi.fn(),
    getBuild: vi.fn(),
  },
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useDockerfiles", () => {
  beforeEach(() => vi.clearAllMocks());

  it("loads dockerfiles via api.list", async () => {
    vi.mocked(dockerfilesApi.list).mockResolvedValueOnce([
      {
        id: "claude-code",
        display_name: "Claude Code",
        description: "",
        parameters: {},
        current_hash: "abc123",
        display_status: "never_built",
        latest_build_id: null,
        created_at: "2026-04-10",
        updated_at: "2026-04-10",
      },
    ]);

    const { result } = renderHook(() => useDockerfiles(), { wrapper });

    await waitFor(() => expect(result.current.dockerfiles).toHaveLength(1));
    expect(result.current.dockerfiles?.[0]?.id).toBe("claude-code");
  });

  it("invalidates cache after create", async () => {
    vi.mocked(dockerfilesApi.list).mockResolvedValue([]);
    vi.mocked(dockerfilesApi.create).mockResolvedValueOnce({
      id: "x",
      display_name: "X",
      description: "",
      parameters: {},
      current_hash: "",
      display_status: "never_built",
      latest_build_id: null,
      created_at: "2026-04-10",
      updated_at: "2026-04-10",
    });

    const { result } = renderHook(() => useDockerfiles(), { wrapper });
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    await result.current.createMutation.mutateAsync({
      id: "x",
      display_name: "X",
    });

    expect(dockerfilesApi.create).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run — expect failure**

Run: `cd frontend && npm test -- tests/hooks/useDockerfiles.test.tsx`

- [ ] **Step 3: Implement `useDockerfiles.ts`**

Create `frontend/src/hooks/useDockerfiles.ts`:

```ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  dockerfilesApi,
  type DockerfileCreate,
  type DockerfileSummary,
  type FileCreate,
  type DockerfileDetail,
} from "@/lib/dockerfilesApi";

const DOCKERFILES_KEY = ["dockerfiles"] as const;

export function useDockerfiles() {
  const qc = useQueryClient();

  const listQuery = useQuery<DockerfileSummary[]>({
    queryKey: DOCKERFILES_KEY,
    queryFn: () => dockerfilesApi.list(),
  });

  const invalidate = (id?: string) => {
    qc.invalidateQueries({ queryKey: DOCKERFILES_KEY });
    if (id) qc.invalidateQueries({ queryKey: ["dockerfile", id] });
  };

  const createMutation = useMutation({
    mutationFn: (payload: DockerfileCreate) => dockerfilesApi.create(payload),
    onSuccess: (data) => invalidate(data.id),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => dockerfilesApi.remove(id),
    onSuccess: (_data, id) => invalidate(id),
  });

  const createFileMutation = useMutation({
    mutationFn: ({
      dockerfileId,
      payload,
    }: {
      dockerfileId: string;
      payload: FileCreate;
    }) => dockerfilesApi.createFile(dockerfileId, payload),
    onSuccess: (_data, vars) => invalidate(vars.dockerfileId),
  });

  const updateFileMutation = useMutation({
    mutationFn: ({
      dockerfileId,
      fileId,
      content,
    }: {
      dockerfileId: string;
      fileId: string;
      content: string;
    }) => dockerfilesApi.updateFile(dockerfileId, fileId, content),
    onSuccess: (_data, vars) => invalidate(vars.dockerfileId),
  });

  const deleteFileMutation = useMutation({
    mutationFn: ({
      dockerfileId,
      fileId,
    }: {
      dockerfileId: string;
      fileId: string;
    }) => dockerfilesApi.deleteFile(dockerfileId, fileId),
    onSuccess: (_data, vars) => invalidate(vars.dockerfileId),
  });

  return {
    dockerfiles: listQuery.data,
    isLoading: listQuery.isLoading,
    error: listQuery.error,
    createMutation,
    deleteMutation,
    createFileMutation,
    updateFileMutation,
    deleteFileMutation,
  };
}

export function useDockerfileDetail(id: string | null) {
  return useQuery<DockerfileDetail>({
    queryKey: ["dockerfile", id],
    queryFn: () => {
      if (!id) throw new Error("id required");
      return dockerfilesApi.get(id);
    },
    enabled: !!id,
  });
}
```

- [ ] **Step 4: Implement `useBuild.ts`**

Create `frontend/src/hooks/useBuild.ts`:

```ts
import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { dockerfilesApi, type BuildSummary } from "@/lib/dockerfilesApi";

/**
 * Polls the backend for build status every 1.5s while status is running/pending.
 * Invalidates the dockerfile detail cache when build completes.
 */
export function useBuild(dockerfileId: string, buildId: string | null) {
  const [build, setBuild] = useState<BuildSummary | null>(null);
  const qc = useQueryClient();

  useEffect(() => {
    if (!buildId) {
      setBuild(null);
      return;
    }
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    async function poll() {
      try {
        const b = await dockerfilesApi.getBuild(dockerfileId, buildId!);
        if (cancelled) return;
        setBuild(b);
        if (b.status === "pending" || b.status === "running") {
          timer = setTimeout(poll, 1500);
        } else {
          qc.invalidateQueries({ queryKey: ["dockerfiles"] });
          qc.invalidateQueries({ queryKey: ["dockerfile", dockerfileId] });
        }
      } catch {
        if (!cancelled) timer = setTimeout(poll, 3000);
      }
    }
    poll();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [dockerfileId, buildId, qc]);

  return build;
}
```

- [ ] **Step 5: Run tests**

Run: `cd frontend && npm test -- tests/hooks/useDockerfiles.test.tsx`
Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/hooks/useDockerfiles.ts frontend/src/hooks/useBuild.ts frontend/tests/hooks/useDockerfiles.test.tsx
git commit -m "feat(m1): useDockerfiles + useBuild hooks with tests"
```

---

### Task 10: `BuildStatusBadge` component (TDD) + `BuildModal`

**Files:**
- Create: `frontend/src/components/BuildStatusBadge.tsx`
- Create: `frontend/src/components/BuildModal.tsx`
- Create: `frontend/tests/components/BuildStatusBadge.test.tsx`

- [ ] **Step 1: Write failing test**

Create `frontend/tests/components/BuildStatusBadge.test.tsx`:

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { BuildStatusBadge } from "@/components/BuildStatusBadge";
import "@/lib/i18n";

describe("BuildStatusBadge", () => {
  it("renders up_to_date with green dot", () => {
    render(<BuildStatusBadge status="up_to_date" />);
    expect(screen.getByText(/à jour/)).toBeInTheDocument();
  });

  it("renders never_built with red dot", () => {
    render(<BuildStatusBadge status="never_built" />);
    expect(screen.getByText(/Jamais compilé/)).toBeInTheDocument();
  });

  it("renders outdated with orange dot", () => {
    render(<BuildStatusBadge status="outdated" />);
    expect(screen.getByText(/obsolète/)).toBeInTheDocument();
  });

  it("renders building with blue dot", () => {
    render(<BuildStatusBadge status="building" />);
    expect(screen.getByText(/Build en cours/)).toBeInTheDocument();
  });

  it("renders failed with red dot", () => {
    render(<BuildStatusBadge status="failed" />);
    expect(screen.getByText(/échoué/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Implement `BuildStatusBadge.tsx`**

Create `frontend/src/components/BuildStatusBadge.tsx`:

```tsx
import { useTranslation } from "react-i18next";
import type { DisplayStatus } from "@/lib/dockerfilesApi";

interface Props {
  status: DisplayStatus;
}

export function BuildStatusBadge({ status }: Props) {
  const { t } = useTranslation();
  return (
    <span style={{ fontSize: "12px", whiteSpace: "nowrap" }}>
      {t(`dockerfiles.status.${status}`)}
    </span>
  );
}
```

- [ ] **Step 3: Run test**

Run: `cd frontend && npm test -- tests/components/BuildStatusBadge.test.tsx`
Expected: 5 passed.

- [ ] **Step 4: Implement `BuildModal.tsx`**

Create `frontend/src/components/BuildModal.tsx`:

```tsx
import { useTranslation } from "react-i18next";
import { useBuild } from "@/hooks/useBuild";

interface Props {
  dockerfileId: string;
  dockerfileName: string;
  buildId: string;
  onClose: () => void;
}

export function BuildModal({ dockerfileId, dockerfileName, buildId, onClose }: Props) {
  const { t } = useTranslation();
  const build = useBuild(dockerfileId, buildId);

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.5)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 1000,
      }}
    >
      <div
        style={{
          background: "white",
          padding: "1.5rem",
          borderRadius: "8px",
          width: "min(900px, 90%)",
          maxHeight: "80vh",
          display: "flex",
          flexDirection: "column",
        }}
      >
        <h2 style={{ margin: 0 }}>
          {t("dockerfiles.build_modal.title", { dockerfile: dockerfileName })}
        </h2>
        {build && (
          <>
            <p style={{ fontSize: "13px", color: "#555" }}>
              <strong>{t("dockerfiles.build_modal.image_tag")}:</strong>{" "}
              <code>{build.image_tag}</code>
            </p>
            <p>
              <strong>Status:</strong>{" "}
              {build.status === "success"
                ? `✅ ${t("dockerfiles.build_modal.success")}`
                : build.status === "failed"
                  ? `❌ ${t("dockerfiles.build_modal.failed")}`
                  : `🔵 ${t("dockerfiles.build_modal.running")}`}
            </p>
            <strong>{t("dockerfiles.build_modal.logs")}</strong>
            <pre
              style={{
                flex: 1,
                overflow: "auto",
                background: "#111",
                color: "#0f0",
                padding: "0.75rem",
                fontSize: "12px",
                margin: "0.5rem 0",
                whiteSpace: "pre-wrap",
              }}
            >
              {build.logs || "..."}
            </pre>
          </>
        )}
        <button type="button" onClick={onClose} style={{ alignSelf: "flex-end" }}>
          {t("dockerfiles.build_modal.close")}
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/BuildStatusBadge.tsx frontend/src/components/BuildModal.tsx frontend/tests/components/BuildStatusBadge.test.tsx
git commit -m "feat(m1): BuildStatusBadge + BuildModal components"
```

---

### Task 11: `DockerfilesPage` + router + nav (TDD)

**Files:**
- Create: `frontend/src/pages/DockerfilesPage.tsx`
- Create: `frontend/tests/pages/DockerfilesPage.test.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/pages/HomePage.tsx`

- [ ] **Step 1: Write failing test**

Create `frontend/tests/pages/DockerfilesPage.test.tsx`:

```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { DockerfilesPage } from "@/pages/DockerfilesPage";
import { dockerfilesApi } from "@/lib/dockerfilesApi";
import "@/lib/i18n";

vi.mock("@/lib/dockerfilesApi", () => ({
  dockerfilesApi: {
    list: vi.fn(),
    get: vi.fn(),
    create: vi.fn(),
    remove: vi.fn(),
    createFile: vi.fn(),
    updateFile: vi.fn(),
    deleteFile: vi.fn(),
    build: vi.fn(),
    getBuild: vi.fn(),
  },
}));

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <DockerfilesPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("DockerfilesPage", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders empty state", async () => {
    vi.mocked(dockerfilesApi.list).mockResolvedValueOnce([]);
    renderPage();
    expect(await screen.findByText(/Aucun dockerfile/)).toBeInTheDocument();
  });

  it("lists dockerfiles with status badge", async () => {
    vi.mocked(dockerfilesApi.list).mockResolvedValueOnce([
      {
        id: "claude-code",
        display_name: "Claude Code",
        description: "",
        parameters: {},
        current_hash: "abc123",
        display_status: "never_built",
        latest_build_id: null,
        created_at: "2026-04-10",
        updated_at: "2026-04-10",
      },
    ]);

    renderPage();

    expect(await screen.findByText("Claude Code")).toBeInTheDocument();
    expect(screen.getByText(/Jamais compilé/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Implement `DockerfilesPage.tsx`**

Create `frontend/src/pages/DockerfilesPage.tsx`:

```tsx
import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  useDockerfiles,
  useDockerfileDetail,
} from "@/hooks/useDockerfiles";
import { BuildStatusBadge } from "@/components/BuildStatusBadge";
import { BuildModal } from "@/components/BuildModal";
import { MarkdownEditor } from "@/components/MarkdownEditor";
import { dockerfilesApi } from "@/lib/dockerfilesApi";
import type { FileSummary } from "@/lib/dockerfilesApi";

export function DockerfilesPage() {
  const { t } = useTranslation();
  const {
    dockerfiles,
    isLoading,
    createMutation,
    deleteMutation,
    createFileMutation,
    updateFileMutation,
    deleteFileMutation,
  } = useDockerfiles();

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<FileSummary | null>(null);
  const [buildId, setBuildId] = useState<string | null>(null);
  const [draftContent, setDraftContent] = useState<string | null>(null);

  const detail = useDockerfileDetail(selectedId);
  const currentDockerfile = detail.data?.dockerfile ?? null;
  const files = detail.data?.files ?? [];

  async function handleCreate() {
    const id = window.prompt(t("dockerfiles.new_dockerfile_id_prompt"));
    if (!id) return;
    const display_name =
      window.prompt(t("dockerfiles.new_dockerfile_name_prompt")) ?? id;
    const created = await createMutation.mutateAsync({ id, display_name });
    setSelectedId(created.id);
  }

  async function handleDelete() {
    if (!selectedId) return;
    if (!window.confirm(t("dockerfiles.confirm_delete", { name: selectedId })))
      return;
    await deleteMutation.mutateAsync(selectedId);
    setSelectedId(null);
    setSelectedFile(null);
  }

  async function handleAddFile() {
    if (!selectedId) return;
    const path = window.prompt(t("dockerfiles.new_file_prompt"));
    if (!path) return;
    const f = await createFileMutation.mutateAsync({
      dockerfileId: selectedId,
      payload: { path, content: "" },
    });
    setSelectedFile(f);
    setDraftContent("");
  }

  async function handleSaveFile() {
    if (!selectedId || !selectedFile || draftContent === null) return;
    await updateFileMutation.mutateAsync({
      dockerfileId: selectedId,
      fileId: selectedFile.id,
      content: draftContent,
    });
    setDraftContent(null);
  }

  async function handleDeleteFile() {
    if (!selectedId || !selectedFile) return;
    await deleteFileMutation.mutateAsync({
      dockerfileId: selectedId,
      fileId: selectedFile.id,
    });
    setSelectedFile(null);
    setDraftContent(null);
  }

  async function handleBuild() {
    if (!selectedId) return;
    const res = await dockerfilesApi.build(selectedId);
    setBuildId(res.id);
  }

  if (isLoading) return <p>{t("secrets.loading")}</p>;

  return (
    <div style={{ display: "flex", height: "100vh" }}>
      {/* Left: dockerfile list */}
      <aside
        style={{
          minWidth: 240,
          borderRight: "1px solid #ddd",
          padding: "1rem",
          background: "#fafafa",
        }}
      >
        <h2>{t("dockerfiles.page_title")}</h2>
        <button type="button" onClick={handleCreate}>
          {t("dockerfiles.add_button")}
        </button>
        {(dockerfiles ?? []).length === 0 ? (
          <p style={{ color: "#999", fontStyle: "italic" }}>
            {t("dockerfiles.no_dockerfiles")}
          </p>
        ) : (
          <ul style={{ listStyle: "none", padding: 0, marginTop: "1rem" }}>
            {dockerfiles?.map((d) => (
              <li key={d.id} style={{ marginBottom: "0.5rem" }}>
                <button
                  type="button"
                  onClick={() => {
                    setSelectedId(d.id);
                    setSelectedFile(null);
                    setDraftContent(null);
                  }}
                  style={{
                    width: "100%",
                    textAlign: "left",
                    padding: "8px",
                    background:
                      selectedId === d.id ? "#e0e7ff" : "transparent",
                    border: "none",
                    cursor: "pointer",
                    display: "flex",
                    flexDirection: "column",
                    gap: "4px",
                  }}
                >
                  <strong>{d.display_name}</strong>
                  <BuildStatusBadge status={d.display_status} />
                </button>
              </li>
            ))}
          </ul>
        )}
        {selectedId && (
          <button
            type="button"
            onClick={handleDelete}
            style={{ marginTop: "2rem", color: "red" }}
          >
            {t("dockerfiles.delete_button")}
          </button>
        )}
      </aside>

      {selectedId && currentDockerfile ? (
        <>
          {/* Middle: files list */}
          <aside
            style={{
              minWidth: 220,
              borderRight: "1px solid #ddd",
              padding: "1rem",
            }}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginBottom: "0.5rem",
              }}
            >
              <strong>Files</strong>
              <button type="button" onClick={handleAddFile}>
                {t("dockerfiles.new_file_button")}
              </button>
            </div>
            {files.length === 0 ? (
              <p style={{ color: "#999", fontStyle: "italic" }}>
                {t("dockerfiles.no_files")}
              </p>
            ) : (
              <ul style={{ listStyle: "none", padding: 0 }}>
                {files.map((f) => (
                  <li key={f.id}>
                    <button
                      type="button"
                      onClick={() => {
                        setSelectedFile(f);
                        setDraftContent(null);
                      }}
                      style={{
                        width: "100%",
                        textAlign: "left",
                        padding: "4px 6px",
                        background:
                          selectedFile?.id === f.id ? "#e0e7ff" : "transparent",
                        border: "none",
                        cursor: "pointer",
                        fontFamily: "monospace",
                        fontSize: "13px",
                      }}
                    >
                      {f.path}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </aside>

          {/* Right: editor */}
          <main style={{ flex: 1, padding: "1.5rem", overflowY: "auto" }}>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginBottom: "1rem",
              }}
            >
              <div>
                <h2 style={{ margin: 0 }}>{currentDockerfile.display_name}</h2>
                <p style={{ fontSize: "12px", color: "#666" }}>
                  {t("dockerfiles.current_hash")}:{" "}
                  <code>{currentDockerfile.current_hash}</code>
                </p>
                <BuildStatusBadge status={currentDockerfile.display_status} />
              </div>
              <button type="button" onClick={handleBuild}>
                {t("dockerfiles.build_button")}
              </button>
            </div>

            {selectedFile ? (
              <div>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    marginBottom: "0.5rem",
                  }}
                >
                  <strong style={{ fontFamily: "monospace" }}>
                    {selectedFile.path}
                  </strong>
                  <span style={{ display: "flex", gap: "0.5rem" }}>
                    {draftContent !== null && (
                      <button type="button" onClick={handleSaveFile}>
                        {t("dockerfiles.save_button")}
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={handleDeleteFile}
                      style={{ color: "red" }}
                    >
                      {t("dockerfiles.delete_button")}
                    </button>
                  </span>
                </div>
                <MarkdownEditor
                  value={draftContent ?? selectedFile.content}
                  onChange={(v) => setDraftContent(v)}
                  minHeight={420}
                />
              </div>
            ) : (
              <p style={{ color: "#888" }}>
                {t("dockerfiles.no_files")} — {t("dockerfiles.new_file_button")}
              </p>
            )}
          </main>
        </>
      ) : (
        <main style={{ flex: 1, padding: "2rem", color: "#888" }}>
          <p>{t("dockerfiles.select_dockerfile")}</p>
        </main>
      )}

      {buildId && selectedId && currentDockerfile && (
        <BuildModal
          dockerfileId={selectedId}
          dockerfileName={currentDockerfile.display_name}
          buildId={buildId}
          onClose={() => setBuildId(null)}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 3: Run test**

Run: `cd frontend && npm test -- tests/pages/DockerfilesPage.test.tsx`
Expected: 2 passed.

- [ ] **Step 4: Add route + nav link**

Edit `frontend/src/App.tsx`:
```tsx
import { DockerfilesPage } from "./pages/DockerfilesPage";
```
In `<Routes>`:
```tsx
      <Route
        path="/dockerfiles"
        element={
          <ProtectedRoute>
            <DockerfilesPage />
          </ProtectedRoute>
        }
      />
```

Edit `frontend/src/pages/HomePage.tsx`, in the `<nav>`:
```tsx
        {" • "}
        <Link to="/dockerfiles">{t("dockerfiles.page_title")}</Link>
```

- [ ] **Step 5: Full frontend suite + TS check**

Run: `cd frontend && npm test && npx tsc --noEmit`
Expected: all tests green, no TS errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/DockerfilesPage.tsx frontend/src/App.tsx frontend/src/pages/HomePage.tsx frontend/tests/pages/DockerfilesPage.test.tsx
git commit -m "feat(m1): DockerfilesPage wired into router with nav link"
```

---

### Task 12: Deploy LXC 201 + smoke test with real claude-code build

- [ ] **Step 1: Deploy**

Run: `./scripts/deploy.sh --rebuild`
Expected: all containers up, backend has `/var/run/docker.sock` mounted.

- [ ] **Step 2: Apply migrations**

Run:
```bash
ssh pve "pct exec 201 -- docker exec agflow-backend python -m agflow.db.migrations"
```
Expected: log shows `applied=['007_dockerfiles', '008_dockerfile_files', '009_dockerfile_builds']` or empty if already applied.

- [ ] **Step 3: Verify docker.sock is accessible from backend container**

Run:
```bash
ssh pve "pct exec 201 -- docker exec agflow-backend ls -la /var/run/docker.sock"
```
Expected: socket file visible, owned by root.

- [ ] **Step 4: Create a minimal dockerfile via curl**

```bash
cd backend
TOKEN=$(curl -s -X POST http://192.168.10.82/api/admin/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@agflow.example.com","password":"agflow-admin-2026"}' \
  | uv run python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl -s -X POST http://192.168.10.82/api/admin/dockerfiles \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"id":"hello","display_name":"Hello smoke test"}'

curl -s -X POST http://192.168.10.82/api/admin/dockerfiles/hello/files \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"path":"Dockerfile","content":"FROM alpine:3.19\nRUN echo hello world > /hello.txt\nCMD [\"cat\", \"/hello.txt\"]"}'

# Trigger the build
BUILD=$(curl -s -X POST http://192.168.10.82/api/admin/dockerfiles/hello/build \
  -H "Authorization: Bearer $TOKEN")
echo "Build: $BUILD"
BUILD_ID=$(echo "$BUILD" | uv run python -c "import sys,json; print(json.load(sys.stdin)['id'])")

# Poll until done (simple loop)
for i in 1 2 3 4 5 6 7 8 9 10; do
  STATUS=$(curl -s -H "Authorization: Bearer $TOKEN" \
    http://192.168.10.82/api/admin/dockerfiles/hello/builds/$BUILD_ID \
    | uv run python -c "import sys,json; b=json.load(sys.stdin); print(b['status'])")
  echo "poll $i: $STATUS"
  [ "$STATUS" = "success" ] && break
  [ "$STATUS" = "failed" ] && break
  sleep 2
done

# Show final logs
curl -s -H "Authorization: Bearer $TOKEN" \
  http://192.168.10.82/api/admin/dockerfiles/hello/builds/$BUILD_ID \
  | uv run python -c "import sys,json; b=json.load(sys.stdin); print('Status:', b['status']); print('Logs:'); print(b['logs'])"
```

Expected: build completes with `status: success`, logs show docker build output, image `agflow-hello:<hash>` was created.

- [ ] **Step 5: Verify image exists on LXC 201**

Run:
```bash
ssh pve "pct exec 201 -- docker images | grep agflow-hello"
```
Expected: 1 line showing the image with its hash tag.

- [ ] **Step 6: Browser walkthrough**

1. Open http://192.168.10.82/
2. Login as admin
3. Navigate to "Dockerfiles (runtimes des agents)" via HomePage nav
4. See "Hello smoke test" in the left rail with 🟢 status
5. Click it → see the `Dockerfile` file
6. Click `Dockerfile` → edit the content (add a comment)
7. Click Save → status should update to 🟠 (outdated)
8. Click Compiler → watch the build modal stream logs → ends with ✅ Succès
9. Status returns to 🟢

- [ ] **Step 7: Cleanup + push**

```bash
# Cleanup the test dockerfile (optional)
curl -s -X DELETE -H "Authorization: Bearer $TOKEN" http://192.168.10.82/api/admin/dockerfiles/hello

git push origin main
```

---

## Verification end-to-end

```bash
# Backend tests (~81 = 60 previous + 21 new)
cd backend && uv run python -m pytest -q
cd backend && uv run ruff check src/ tests/

# Frontend tests (~35 = 30 previous + ~5 new)
cd frontend && npm test
cd frontend && npx tsc --noEmit

# Prod: browser walkthrough above
```

---

## Self-Review Checklist

**1. Spec coverage (Module 1 from specs/home.md):**
- ✅ CRUD des Dockerfiles (entités agents)
- ✅ Multiple files per dockerfile (Dockerfile, entrypoint.sh, run.cmd.md, autres)
- ✅ Coloration syntaxique → simple textarea monospace (Monaco deferred, documented)
- ✅ Sidebar avec liste des agents et leurs fichiers
- ✅ Sauvegarder, Compiler, Supprimer actions
- ✅ Tagging déterministe `agflow-{agent}:{hash}` avec hash = SHA256(Dockerfile + *.sh triés)
- ✅ Docker build via aiodocker avec stream des logs en base
- ✅ Badge statut (🟢 à jour / 🟠 obsolète / 🔴 non buildé / 🔴 échoué / 🔵 en cours)
- ✅ Paramètres Dockerfile stockés en JSONB (résolution dans M4)
- ⚠ **Protocole entrypoint standardisé** — documenté en tant que convention (le code doit suivre le contrat JSON stdin + emit_event stdout). Phase 3 ne valide pas ce protocole automatiquement ; le smoke test utilise un `FROM alpine` simple. La vérification du protocole viendra en M4 quand on lancera réellement un agent.
- ⚠ **Volumes normalisés** (`/app`, `/app/skills`, `/app/config`, `/app/output`) — documentés comme convention pour que le créateur du Dockerfile déclare les VOLUME. Pas d'enforcement automatique en Phase 3.
- ⚠ **Syntax templating `${VAR:-default}`** — stocké en `parameters` JSONB, résolution à la composition M4.

**2. Placeholder scan:** Every step has concrete code, commands, and verification. Deferred items are documented explicitly.

**3. Type consistency:** 
- Backend `DockerfileSummary.display_status` enum matches frontend `DisplayStatus` type
- `BuildStatus` enum matches backend `BuildSummary.status`
- API paths consistent: `/api/admin/dockerfiles/{id}/files/{file_id}` same in backend router, frontend client, and tests
- `current_hash` is 12 chars (computed in `build_service.compute_hash`, assumed in frontend display)

---

## Execution Handoff

Ready to execute inline with `superpowers:executing-plans`. Expected duration: comparable to M0 and M2 (~45-60 min of tool operations). The main risk is **docker.sock mount permissions in LXC** — if `/var/run/docker.sock` isn't accessible from inside the backend container, the build will fail with a permission error. Verified in Task 12 Step 3 before the smoke test.
