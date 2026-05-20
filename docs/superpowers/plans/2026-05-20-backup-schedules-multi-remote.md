# Backup schedules multi-remote + wizard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Référence détaillée** : `docs/superpowers/specs/2026-05-20-backup-schedules-multi-remote-design.md` (spec validée, commit `c18f908`).

**Goal:** Étendre `backup_schedules_full` au multi-remote (1 backup → N pushes), tracer chaque push en DB, ajouter un wizard 3 phases (récurrence → moment → destinations), et permettre la suppression optionnelle du fichier local après pushes réussis (`keep_local=false`).

**Architecture:** Pattern mirror PITR : join table `backup_schedule_full_remotes` (config) + table `local_backup_pushes` (history par couple backup×remote). Service `local_backup_pushes_service.py` dédié (~150 LoC). Refactor `backup_job_runner.py` pour boucle de pushes séquentielle + suppression conditionnelle du fichier local. UI : Wizard stepper 3 phases (modal Dialog) qui compose un cron `{minute} * * * *` ou `0 {hour} * * *`. Affichage des badges push par remote dans `LocalBackupsSection`.

**Tech Stack:** Python 3.12 + asyncpg + Pydantic v2 + FastAPI + structlog + APScheduler + croniter + pytest / Postgres 16 / Vite + React 18 + TanStack Query + shadcn/ui + i18next + Vitest

---

## File Structure

### Backend — créés

| Fichier | Responsabilité |
|---|---|
| `backend/migrations/114_backup_schedules_multi_remote.sql` | 2 tables (`backup_schedule_full_remotes`, `local_backup_pushes`) + 2 colonnes ALTER (`keep_local`, `local_file_present`) + migration data + DROP COLUMN |
| `backend/src/agflow/schemas/local_backup_pushes.py` | Pydantic `LocalBackupPushSummary` |
| `backend/src/agflow/services/local_backup_pushes_service.py` | seed_pushes, list_pushes, push_all_pending, push_one + exceptions |
| `backend/tests/db/test_migration_114_multi_remote.py` | Tables créées, colonnes ajoutées, migration data |
| `backend/tests/services/test_local_backup_pushes_service.py` | seed, push_all happy + partial, push_one idempotent, file missing |

### Backend — modifiés

| Fichier | Modification |
|---|---|
| `backend/src/agflow/schemas/backup_schedules.py` | `FullScheduleSummary`/`CreateFull`/`UpdateFull` : `remote_connection_id` → `remote_connection_ids: list[UUID]` + `keep_local: bool` |
| `backend/src/agflow/services/backup_schedules_service.py` | Signatures CRUD adaptées + SELECT avec JOIN sur la join table + validation `EmptyDestinationsError` |
| `backend/src/agflow/services/backup_job_runner.py` | Création backup → seed pushes → push_all_pending → delete file si `keep_local=false ∧ all_ok` |
| `backend/src/agflow/services/local_backups_service.py` | + `delete_file_only(id)` (préserve la row, supprime juste le fichier) ; `prune_old_backups` skip rows sans fichier |
| `backend/src/agflow/api/admin/backup_schedules.py` | Payloads adaptés (`remote_connection_ids` + `keep_local`) |
| `backend/src/agflow/api/admin/local_backups.py` | + 2 endpoints (`GET /local-backups/{id}/pushes`, `POST /local-backups/{id}/push/{remote_id}`) + champ `pushes` dans GET list |
| `backend/tests/services/test_backup_schedules_service.py` | Adapté pour signatures multi-remote |
| `backend/tests/services/test_backup_job_runner.py` | Cas multi-remote happy + partial + keep_local=false |
| `backend/tests/api/test_admin_backup_schedules.py` | Adapté pour payloads multi-remote |
| `backend/tests/api/test_admin_local_backups.py` | + tests endpoints pushes |

### Frontend — créés

| Fichier | Responsabilité |
|---|---|
| `frontend/src/components/backups/ScheduleWizard.tsx` | Modal Dialog 3 steps (récurrence → moment → destinations) |
| `frontend/src/lib/cronWizard.ts` | `buildCron` + `parseCron` + `formatCronHuman` (helpers purs) |
| `frontend/src/lib/cronWizard.test.ts` | Tests des 3 helpers |
| `frontend/src/components/backups/__tests__/ScheduleWizard.test.tsx` | Tests Vitest navigation + validation + parsing |
| `frontend/src/lib/localBackupPushesApi.ts` | listPushes + pushBackup (re-push) |

### Frontend — modifiés

| Fichier | Modification |
|---|---|
| `frontend/src/lib/backupSchedulesApi.ts` | `FullScheduleSummary` + payloads : `remote_connection_ids: string[]` + `keep_local: boolean` |
| `frontend/src/lib/backupsApi.ts` | `LocalBackup.pushes: LocalBackupPush[]` |
| `frontend/src/components/backups/FullSchedulesSection.tsx` | Le bouton « + Ajouter » et « Édition » ouvrent le Wizard ; colonne « Récurrence » utilise `formatCronHuman` ; colonne « Destination » affiche badges multi-remote + flag local |
| `frontend/src/components/backups/LocalBackupsSection.tsx` | Colonne « Pushes » avec badges par remote + menu re-push + état grisé si `local_file_present=false` |
| `frontend/src/i18n/fr.json` | + ~30 clés `backups.wizard.*` et `backups.pushes.*` |
| `frontend/src/i18n/en.json` | mêmes clés EN |

---

## LOT 1 — DB + services backend (P1)

### Task 1 : Migration 114 + test

**Files:**
- Create: `backend/migrations/114_backup_schedules_multi_remote.sql`
- Create: `backend/tests/db/test_migration_114_multi_remote.py`

- [ ] **Step 1 : Écrire le test (TDD red)**

```python
# backend/tests/db/test_migration_114_multi_remote.py
"""Migration 114 — multi-remote backup_schedules_full + push history."""
from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from asyncpg import CheckViolationError, Connection

from agflow.db.pool import get_pool
from tests._db_reset import reset_schema_and_migrate

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def fresh_db() -> AsyncIterator[Connection]:
    await reset_schema_and_migrate()
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


async def test_join_table_exists(fresh_db):
    table = await fresh_db.fetchval(
        "SELECT to_regclass('public.backup_schedule_full_remotes')"
    )
    assert table is not None


async def test_pushes_table_exists(fresh_db):
    table = await fresh_db.fetchval("SELECT to_regclass('public.local_backup_pushes')")
    assert table is not None


async def test_keep_local_column_exists(fresh_db):
    col = await fresh_db.fetchval(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='backup_schedules_full' AND column_name='keep_local'"
    )
    assert col == "keep_local"


async def test_local_file_present_column_exists(fresh_db):
    col = await fresh_db.fetchval(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='local_backups' AND column_name='local_file_present'"
    )
    assert col == "local_file_present"


async def test_remote_connection_id_column_dropped(fresh_db):
    col = await fresh_db.fetchval(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='backup_schedules_full' AND column_name='remote_connection_id'"
    )
    assert col is None


async def test_keep_local_default_true(fresh_db):
    # Seed un schedule (sans remote — local-only) après la migration
    sid = await fresh_db.fetchval(
        "INSERT INTO backup_schedules_full (name, cron_expr) "
        "VALUES ('test', '0 3 * * *') RETURNING id"
    )
    row = await fresh_db.fetchrow(
        "SELECT keep_local FROM backup_schedules_full WHERE id = $1", sid
    )
    assert row["keep_local"] is True


async def test_pushes_status_check_constraint(fresh_db):
    """CHECK status interdit les valeurs hors enum."""
    bid = await fresh_db.fetchval(
        "INSERT INTO local_backups (filename, file_path, size_bytes, status) "
        "VALUES ('t.dump', '/t', 1, 'ok') RETURNING id"
    )
    rid = await fresh_db.fetchval(
        "INSERT INTO remote_backup_connections (name, kind, config) "
        "VALUES ('test', 'sftp', '{}'::jsonb) RETURNING id"
    )
    with pytest.raises(CheckViolationError):
        await fresh_db.execute(
            "INSERT INTO local_backup_pushes (local_backup_id, remote_connection_id, status) "
            "VALUES ($1, $2, 'invalid')",
            bid, rid,
        )
```

- [ ] **Step 2 : Run, échoue (migration absente)**

```bash
cd backend && uv run pytest tests/db/test_migration_114_multi_remote.py -v
```

Expected : FAIL / ERROR (LXC unreachable → DONE_WITH_CONCERNS acceptable).

- [ ] **Step 3 : Écrire la migration**

```sql
-- backend/migrations/114_backup_schedules_multi_remote.sql
-- Multi-remote pour backup_schedules_full + push history par remote

CREATE TABLE backup_schedule_full_remotes (
    schedule_id          uuid NOT NULL REFERENCES backup_schedules_full(id) ON DELETE CASCADE,
    remote_connection_id uuid NOT NULL REFERENCES remote_backup_connections(id) ON DELETE CASCADE,
    created_at           timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (schedule_id, remote_connection_id)
);

CREATE INDEX idx_backup_schedule_full_remotes_remote
    ON backup_schedule_full_remotes (remote_connection_id);

CREATE TABLE local_backup_pushes (
    id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    local_backup_id      uuid NOT NULL REFERENCES local_backups(id) ON DELETE RESTRICT,
    remote_connection_id uuid NOT NULL REFERENCES remote_backup_connections(id) ON DELETE RESTRICT,
    status               text NOT NULL CHECK (status IN ('pending', 'pushing', 'ok', 'failed')),
    pushed_at            timestamptz,
    error                text,
    remote_path          text,
    size_bytes           bigint,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now(),
    UNIQUE (local_backup_id, remote_connection_id)
);

CREATE INDEX idx_local_backup_pushes_local
    ON local_backup_pushes (local_backup_id);
CREATE INDEX idx_local_backup_pushes_remote
    ON local_backup_pushes (remote_connection_id);

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_local_backup_pushes_updated_at') THEN
        CREATE TRIGGER trg_local_backup_pushes_updated_at
            BEFORE UPDATE ON local_backup_pushes
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
END $$;

ALTER TABLE backup_schedules_full
    ADD COLUMN keep_local boolean NOT NULL DEFAULT true;

ALTER TABLE local_backups
    ADD COLUMN local_file_present boolean NOT NULL DEFAULT true;

INSERT INTO backup_schedule_full_remotes (schedule_id, remote_connection_id)
SELECT id, remote_connection_id
FROM backup_schedules_full
WHERE remote_connection_id IS NOT NULL;

ALTER TABLE backup_schedules_full DROP COLUMN remote_connection_id;
```

- [ ] **Step 4 : Run tests, doivent passer**

```bash
cd backend && uv run pytest tests/db/test_migration_114_multi_remote.py -v
```

Expected : 7 PASS (DB OK) ou DONE_WITH_CONCERNS si DB unreachable.

- [ ] **Step 5 : Commit**

```bash
git add backend/migrations/114_backup_schedules_multi_remote.sql backend/tests/db/test_migration_114_multi_remote.py
git commit -m "feat(backup-db): migration 114 — multi-remote backup_schedules + push history"
```

### Task 2 : Schemas Pydantic adaptés

**Files:**
- Modify: `backend/src/agflow/schemas/backup_schedules.py`
- Create: `backend/src/agflow/schemas/local_backup_pushes.py`

- [ ] **Step 1 : Adapter `backup_schedules.py`**

Lire le fichier existant. Pour chaque classe `FullScheduleSummary`, `CreateFullPayload`, `UpdateFullPayload`, remplacer :
- `remote_connection_id: UUID | None` → `remote_connection_ids: list[UUID]` (default `[]` pour Create)
- Ajouter `keep_local: bool` (default `True` pour Create)

Cible pour `FullScheduleSummary` :

```python
class FullScheduleSummary(BaseModel):
    id: UUID
    name: str
    cron_expr: str
    remote_connection_ids: list[UUID]
    keep_local: bool
    retention_count: int
    enabled: bool
    last_run_at: datetime | None
    last_run_status: Literal["ok", "failed"] | None
    last_run_error: str | None
    created_at: datetime
    updated_at: datetime
```

Cible pour `CreateFullPayload` :

```python
class CreateFullPayload(BaseModel):
    name: str
    cron_expr: str
    remote_connection_ids: list[UUID] = []
    keep_local: bool = True
    retention_count: int = 10
    enabled: bool = True
```

Cible pour `UpdateFullPayload` :

```python
class UpdateFullPayload(BaseModel):
    name: str | None = None
    cron_expr: str | None = None
    remote_connection_ids: list[UUID] | None = None
    keep_local: bool | None = None
    retention_count: int | None = Field(default=None, ge=1)
    enabled: bool | None = None
```

- [ ] **Step 2 : Créer `local_backup_pushes.py`**

```python
# backend/src/agflow/schemas/local_backup_pushes.py
"""DTO pour l'historique des pushes (1 backup × N remotes)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel


class LocalBackupPushSummary(BaseModel):
    id: UUID
    local_backup_id: UUID
    remote_connection_id: UUID
    remote_connection_name: str
    status: Literal["pending", "pushing", "ok", "failed"]
    pushed_at: datetime | None
    error: str | None
    remote_path: str | None
    size_bytes: int | None
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 3 : Vérifier import**

```bash
cd backend && uv run python -c "from agflow.schemas.backup_schedules import FullScheduleSummary, CreateFullPayload, UpdateFullPayload; from agflow.schemas.local_backup_pushes import LocalBackupPushSummary; print('ok')"
```

Expected : `ok`.

- [ ] **Step 4 : Lint**

```bash
cd backend && uv run ruff check src/agflow/schemas/backup_schedules.py src/agflow/schemas/local_backup_pushes.py
```

- [ ] **Step 5 : Commit**

```bash
git add backend/src/agflow/schemas/backup_schedules.py backend/src/agflow/schemas/local_backup_pushes.py
git commit -m "feat(backup-services): schemas multi-remote (remote_connection_ids + keep_local + LocalBackupPushSummary)"
```

### Task 3 : `backup_schedules_service` — adaptation multi-remote

**Files:**
- Modify: `backend/src/agflow/services/backup_schedules_service.py`
- Modify: `backend/tests/services/test_backup_schedules_service.py`

- [ ] **Step 1 : Adapter le service**

Modifier `backend/src/agflow/services/backup_schedules_service.py` :

1. **Ajouter l'exception** :

```python
class EmptyDestinationsError(ValueError):
    """Levée si keep_local=false ET aucune remote_connection_id."""
```

2. **Remplacer la signature de `create_full_schedule`** :

```python
async def create_full_schedule(
    *,
    name: str,
    cron_expr: str,
    remote_connection_ids: list[UUID],
    keep_local: bool,
    retention_count: int,
    enabled: bool,
    actor_user_id: UUID | None,
) -> FullScheduleSummary:
    # 1) Validation cron
    try:
        croniter(cron_expr)
    except (CroniterBadCronError, ValueError) as err:
        raise InvalidCronError(f"invalid cron: {cron_expr!r}") from err

    # 2) Validation destinations
    if not keep_local and not remote_connection_ids:
        raise EmptyDestinationsError("at least one destination required (local or remote)")

    # 3) Validation chaque remote existe
    for rid in remote_connection_ids:
        conn = await remote_backup_connections_service.get_connection(rid)
        if conn is None:
            raise RemoteNotFoundError(str(rid))

    # 4) Transaction INSERT schedule + INSERT N remotes
    db_pool = await get_pool()
    async with db_pool.acquire() as conn, conn.transaction():
        row = await conn.fetchrow(
            "INSERT INTO backup_schedules_full "
            "(name, cron_expr, retention_count, enabled, keep_local, created_by_user_id) "
            "VALUES ($1, $2, $3, $4, $5, $6) RETURNING id",
            name, cron_expr, retention_count, enabled, keep_local, actor_user_id,
        )
        schedule_id = row["id"]
        for rid in remote_connection_ids:
            await conn.execute(
                "INSERT INTO backup_schedule_full_remotes (schedule_id, remote_connection_id) "
                "VALUES ($1, $2)",
                schedule_id, rid,
            )

    log.info("backup_schedules.full.created",
             schedule_id=str(schedule_id),
             remote_count=len(remote_connection_ids),
             keep_local=keep_local)
    return await get_full_schedule(schedule_id)
```

3. **Remplacer la signature de `update_full_schedule`** :

```python
async def update_full_schedule(
    id: UUID,
    *,
    name: str | None = None,
    cron_expr: str | None = None,
    remote_connection_ids: list[UUID] | None = None,
    keep_local: bool | None = None,
    retention_count: int | None = None,
    enabled: bool | None = None,
) -> FullScheduleSummary:
    # Validation cron si fourni
    if cron_expr is not None:
        try:
            croniter(cron_expr)
        except (CroniterBadCronError, ValueError) as err:
            raise InvalidCronError(f"invalid cron: {cron_expr!r}") from err

    # Validation chaque remote si fourni
    if remote_connection_ids is not None:
        for rid in remote_connection_ids:
            conn = await remote_backup_connections_service.get_connection(rid)
            if conn is None:
                raise RemoteNotFoundError(str(rid))

    # Pour valider keep_local + remotes, il faut connaître l'état actuel si l'un des deux n'est pas fourni
    current = await get_full_schedule(id)
    final_keep_local = keep_local if keep_local is not None else current.keep_local
    final_remote_ids = remote_connection_ids if remote_connection_ids is not None else current.remote_connection_ids
    if not final_keep_local and not final_remote_ids:
        raise EmptyDestinationsError("at least one destination required (local or remote)")

    db_pool = await get_pool()
    async with db_pool.acquire() as conn, conn.transaction():
        sets, params = [], []
        if name is not None:
            params.append(name); sets.append(f"name = ${len(params)}")
        if cron_expr is not None:
            params.append(cron_expr); sets.append(f"cron_expr = ${len(params)}")
        if retention_count is not None:
            params.append(retention_count); sets.append(f"retention_count = ${len(params)}")
        if enabled is not None:
            params.append(enabled); sets.append(f"enabled = ${len(params)}")
        if keep_local is not None:
            params.append(keep_local); sets.append(f"keep_local = ${len(params)}")
        if sets:
            params.append(id)
            await conn.execute(
                f"UPDATE backup_schedules_full SET {', '.join(sets)} WHERE id = ${len(params)}",
                *params,
            )

        if remote_connection_ids is not None:
            await conn.execute(
                "DELETE FROM backup_schedule_full_remotes WHERE schedule_id = $1", id
            )
            for rid in remote_connection_ids:
                await conn.execute(
                    "INSERT INTO backup_schedule_full_remotes (schedule_id, remote_connection_id) "
                    "VALUES ($1, $2)",
                    id, rid,
                )

    return await get_full_schedule(id)
```

4. **Adapter `get_full_schedule` et `list_full_schedules`** pour JOIN sur la join table :

```python
_FULL_SELECT_WITH_REMOTES = """
SELECT s.id, s.name, s.cron_expr, s.retention_count, s.enabled, s.keep_local,
       s.last_run_at, s.last_run_status, s.last_run_error,
       s.created_at, s.updated_at,
       coalesce(
         array_agg(r.remote_connection_id) FILTER (WHERE r.remote_connection_id IS NOT NULL),
         ARRAY[]::uuid[]
       ) AS remote_connection_ids
FROM backup_schedules_full s
LEFT JOIN backup_schedule_full_remotes r ON r.schedule_id = s.id
"""


async def get_full_schedule(id: UUID) -> FullScheduleSummary:
    row = await fetch_one(
        _FULL_SELECT_WITH_REMOTES + " WHERE s.id = $1 GROUP BY s.id",
        id,
    )
    if row is None:
        raise ScheduleNotFoundError(str(id))
    return FullScheduleSummary(**row)


async def list_full_schedules() -> list[FullScheduleSummary]:
    rows = await fetch_all(
        _FULL_SELECT_WITH_REMOTES + " GROUP BY s.id ORDER BY s.created_at DESC"
    )
    return [FullScheduleSummary(**r) for r in rows]
```

- [ ] **Step 2 : Adapter les tests existants**

Lire `backend/tests/services/test_backup_schedules_service.py`. Remplacer tous les `remote_connection_id=uuid` par `remote_connection_ids=[uuid]` ou `remote_connection_ids=[]` selon le cas. Ajouter le param `keep_local=True` aux create.

Ajouter ces tests :

```python
async def test_create_full_schedule_rejects_empty_destinations():
    """keep_local=false + remote_connection_ids=[] → EmptyDestinationsError."""
    from tests._db_reset import reset_schema_and_migrate
    await reset_schema_and_migrate()
    from agflow.services.backup_schedules_service import EmptyDestinationsError

    with pytest.raises(EmptyDestinationsError):
        await backup_schedules_service.create_full_schedule(
            name="bad",
            cron_expr="0 3 * * *",
            remote_connection_ids=[],
            keep_local=False,
            retention_count=10,
            enabled=True,
            actor_user_id=None,
        )


async def test_update_full_schedule_replaces_remote_list():
    """update avec remote_connection_ids=[r2] remplace [r1] par [r2]."""
    from tests._db_reset import reset_schema_and_migrate
    from agflow.db.pool import fetch_one
    await reset_schema_and_migrate()

    # Seed 2 remotes
    r1 = (await fetch_one(
        "INSERT INTO remote_backup_connections (name, kind, config) "
        "VALUES ('r1', 'sftp', '{}'::jsonb) RETURNING id"
    ))["id"]
    r2 = (await fetch_one(
        "INSERT INTO remote_backup_connections (name, kind, config) "
        "VALUES ('r2', 'sftp', '{}'::jsonb) RETURNING id"
    ))["id"]

    sched = await backup_schedules_service.create_full_schedule(
        name="s", cron_expr="0 3 * * *",
        remote_connection_ids=[r1], keep_local=True,
        retention_count=10, enabled=True, actor_user_id=None,
    )
    await backup_schedules_service.update_full_schedule(
        sched.id, remote_connection_ids=[r2]
    )
    refreshed = await backup_schedules_service.get_full_schedule(sched.id)
    assert refreshed.remote_connection_ids == [r2]
```

- [ ] **Step 3 : Run, doit passer**

```bash
cd backend && uv run pytest tests/services/test_backup_schedules_service.py -v
```

Expected : tous PASS (DB OK) ou DONE_WITH_CONCERNS.

- [ ] **Step 4 : Lint**

```bash
cd backend && uv run ruff check src/agflow/services/backup_schedules_service.py tests/services/test_backup_schedules_service.py
```

- [ ] **Step 5 : Commit**

```bash
git add backend/src/agflow/services/backup_schedules_service.py backend/tests/services/test_backup_schedules_service.py
git commit -m "feat(backup-services): backup_schedules_service.{create,update,get,list} multi-remote + EmptyDestinationsError"
```

### Task 4 : `local_backup_pushes_service` (nouveau)

**Files:**
- Create: `backend/src/agflow/services/local_backup_pushes_service.py`
- Create: `backend/tests/services/test_local_backup_pushes_service.py`

- [ ] **Step 1 : Écrire les tests (TDD red)**

```python
# backend/tests/services/test_local_backup_pushes_service.py
"""Tests pour local_backup_pushes_service."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from agflow.db.pool import execute, fetch_one
from agflow.services import local_backup_pushes_service
from agflow.services.local_backup_pushes_service import (
    LocalFileMissingError,
    PushNotFoundError,
)
from tests._db_reset import reset_schema_and_migrate

pytestmark = pytest.mark.asyncio


async def _seed_backup_and_remote() -> tuple:
    """Insère 1 local_backup + 1 remote, retourne (backup_id, remote_id)."""
    await reset_schema_and_migrate()
    bb = await fetch_one(
        "INSERT INTO local_backups (filename, file_path, size_bytes, status) "
        "VALUES ('t.dump', '/tmp/t.dump', 1024, 'ok') RETURNING id"
    )
    rm = await fetch_one(
        "INSERT INTO remote_backup_connections (name, kind, config) "
        "VALUES ('r', 'sftp', '{}'::jsonb) RETURNING id"
    )
    return bb["id"], rm["id"]


async def test_seed_pushes_inserts_one_row_per_remote():
    bid, rid = await _seed_backup_and_remote()
    await local_backup_pushes_service.seed_pushes(backup_id=bid, remote_ids=[rid])
    row = await fetch_one(
        "SELECT status FROM local_backup_pushes WHERE local_backup_id=$1 AND remote_connection_id=$2",
        bid, rid,
    )
    assert row["status"] == "pending"


async def test_seed_pushes_idempotent_on_conflict():
    bid, rid = await _seed_backup_and_remote()
    await local_backup_pushes_service.seed_pushes(backup_id=bid, remote_ids=[rid])
    # Re-seed : ne doit pas planter (ON CONFLICT DO NOTHING)
    await local_backup_pushes_service.seed_pushes(backup_id=bid, remote_ids=[rid])
    count = await fetch_one(
        "SELECT count(*)::int AS n FROM local_backup_pushes WHERE local_backup_id=$1", bid
    )
    assert count["n"] == 1


async def test_list_pushes_with_remote_name():
    bid, rid = await _seed_backup_and_remote()
    await local_backup_pushes_service.seed_pushes(backup_id=bid, remote_ids=[rid])
    pushes = await local_backup_pushes_service.list_pushes(bid)
    assert len(pushes) == 1
    assert pushes[0].remote_connection_name == "r"
    assert pushes[0].status == "pending"


async def test_push_all_pending_happy_marks_ok():
    bid, rid = await _seed_backup_and_remote()
    await local_backup_pushes_service.seed_pushes(backup_id=bid, remote_ids=[rid])

    fake_provider = AsyncMock()
    fake_provider.upload_stream = AsyncMock(return_value=1024)

    with patch(
        "agflow.services.local_backup_pushes_service._provider_for",
        new=AsyncMock(return_value=fake_provider),
    ):
        all_ok = await local_backup_pushes_service.push_all_pending(backup_id=bid)
    assert all_ok is True
    row = await fetch_one(
        "SELECT status, remote_path, size_bytes FROM local_backup_pushes "
        "WHERE local_backup_id=$1", bid,
    )
    assert row["status"] == "ok"
    assert row["size_bytes"] == 1024


async def test_push_all_pending_partial_fail_returns_false():
    bid, rid = await _seed_backup_and_remote()
    rm2 = await fetch_one(
        "INSERT INTO remote_backup_connections (name, kind, config) "
        "VALUES ('r2', 'sftp', '{}'::jsonb) RETURNING id"
    )
    await local_backup_pushes_service.seed_pushes(
        backup_id=bid, remote_ids=[rid, rm2["id"]]
    )

    # Premier provider OK, deuxième KO
    providers = [
        AsyncMock(upload_stream=AsyncMock(return_value=1024)),
        AsyncMock(upload_stream=AsyncMock(side_effect=RuntimeError("net down"))),
    ]
    call_count = {"i": 0}

    async def _fake_provider_for(*args, **kwargs):
        p = providers[call_count["i"]]
        call_count["i"] += 1
        return p

    with patch(
        "agflow.services.local_backup_pushes_service._provider_for",
        side_effect=_fake_provider_for,
    ):
        all_ok = await local_backup_pushes_service.push_all_pending(backup_id=bid)

    assert all_ok is False
    rows = await fetch_one(
        "SELECT count(*) FILTER (WHERE status='ok') AS ok_n, "
        "count(*) FILTER (WHERE status='failed') AS fail_n "
        "FROM local_backup_pushes WHERE local_backup_id=$1",
        bid,
    )
    assert rows["ok_n"] == 1
    assert rows["fail_n"] == 1


async def test_push_one_idempotent_when_already_ok():
    bid, rid = await _seed_backup_and_remote()
    await local_backup_pushes_service.seed_pushes(backup_id=bid, remote_ids=[rid])
    await execute(
        "UPDATE local_backup_pushes SET status='ok' WHERE local_backup_id=$1", bid
    )

    fake_provider = AsyncMock()
    with patch(
        "agflow.services.local_backup_pushes_service._provider_for",
        new=AsyncMock(return_value=fake_provider),
    ):
        await local_backup_pushes_service.push_one(backup_id=bid, remote_id=rid)
    # Le provider n'a pas été appelé (idempotent)
    fake_provider.upload_stream.assert_not_called()


async def test_push_one_404_when_push_not_found():
    await reset_schema_and_migrate()
    with pytest.raises(PushNotFoundError):
        await local_backup_pushes_service.push_one(
            backup_id=uuid4(), remote_id=uuid4()
        )


async def test_push_one_409_when_local_file_missing():
    bid, rid = await _seed_backup_and_remote()
    await local_backup_pushes_service.seed_pushes(backup_id=bid, remote_ids=[rid])
    await execute(
        "UPDATE local_backups SET local_file_present=false WHERE id=$1", bid
    )
    with pytest.raises(LocalFileMissingError):
        await local_backup_pushes_service.push_one(backup_id=bid, remote_id=rid)
```

- [ ] **Step 2 : Run, échoue (module absent)**

```bash
cd backend && uv run pytest tests/services/test_local_backup_pushes_service.py -v
```

- [ ] **Step 3 : Écrire le service**

```python
# backend/src/agflow/services/local_backup_pushes_service.py
"""Push history per remote pour les backups locaux."""
from __future__ import annotations

from pathlib import Path
from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.schemas.local_backup_pushes import LocalBackupPushSummary

log = structlog.get_logger(__name__)


class PushNotFoundError(LookupError):
    """Aucune entrée local_backup_pushes pour (backup, remote)."""


class LocalFileMissingError(RuntimeError):
    """Le fichier local est absent (local_file_present=false ou row backup absente)."""


async def seed_pushes(*, backup_id: UUID, remote_ids: list[UUID]) -> None:
    """INSERT 1 row 'pending' par remote. ON CONFLICT DO NOTHING (idempotent)."""
    for rid in remote_ids:
        await execute(
            "INSERT INTO local_backup_pushes (local_backup_id, remote_connection_id, status) "
            "VALUES ($1, $2, 'pending') "
            "ON CONFLICT (local_backup_id, remote_connection_id) DO NOTHING",
            backup_id, rid,
        )


async def list_pushes(backup_id: UUID) -> list[LocalBackupPushSummary]:
    rows = await fetch_all(
        """
        SELECT p.id, p.local_backup_id, p.remote_connection_id, r.name AS remote_connection_name,
               p.status, p.pushed_at, p.error, p.remote_path, p.size_bytes,
               p.created_at, p.updated_at
        FROM local_backup_pushes p
        JOIN remote_backup_connections r ON r.id = p.remote_connection_id
        WHERE p.local_backup_id = $1
        ORDER BY p.created_at ASC
        """,
        backup_id,
    )
    return [LocalBackupPushSummary(**r) for r in rows]


async def push_all_pending(*, backup_id: UUID) -> bool:
    """Itère sur les pushes 'pending' du backup, les pousse séquentiellement.
    Erreur par-remote catchée. Retourne True si TOUS sont 'ok' au final."""
    pending = await fetch_all(
        "SELECT remote_connection_id FROM local_backup_pushes "
        "WHERE local_backup_id = $1 AND status IN ('pending', 'failed')",
        backup_id,
    )
    all_ok = True
    for row in pending:
        try:
            await push_one(backup_id=backup_id, remote_id=row["remote_connection_id"])
        except Exception as exc:
            log.error("local_backup_push.failed",
                      backup_id=str(backup_id),
                      remote_id=str(row["remote_connection_id"]),
                      error=str(exc))
            all_ok = False

    # Final check : tous les pushes du backup sont 'ok' ?
    not_ok = await fetch_one(
        "SELECT count(*)::int AS n FROM local_backup_pushes "
        "WHERE local_backup_id = $1 AND status != 'ok'",
        backup_id,
    )
    return (not_ok["n"] == 0) if all_ok else False


async def push_one(*, backup_id: UUID, remote_id: UUID) -> LocalBackupPushSummary:
    """Re-push manuel d'un backup vers une remote.
    Idempotent si status='ok'. Lève LocalFileMissingError si le fichier est absent."""
    push_row = await fetch_one(
        "SELECT id, status FROM local_backup_pushes "
        "WHERE local_backup_id = $1 AND remote_connection_id = $2",
        backup_id, remote_id,
    )
    if push_row is None:
        raise PushNotFoundError(f"{backup_id}/{remote_id}")
    if push_row["status"] == "ok":
        return (await list_pushes(backup_id))[0]  # idempotent

    backup = await fetch_one(
        "SELECT file_path, filename, local_file_present FROM local_backups WHERE id = $1",
        backup_id,
    )
    if backup is None or not backup["local_file_present"]:
        raise LocalFileMissingError(str(backup_id))

    await execute(
        "UPDATE local_backup_pushes SET status='pushing', error=NULL WHERE id=$1",
        push_row["id"],
    )

    try:
        provider = await _provider_for(remote_id)
        remote_path, size_bytes = await _push_to_remote(
            backup_id=backup_id,
            provider=provider,
            local_file_path=backup["file_path"],
            filename=backup["filename"],
        )
        await execute(
            "UPDATE local_backup_pushes SET status='ok', pushed_at=now(), "
            "remote_path=$2, size_bytes=$3 WHERE id=$1",
            push_row["id"], remote_path, size_bytes,
        )
        log.info("local_backup_push.ok",
                 backup_id=str(backup_id), remote_id=str(remote_id),
                 remote_path=remote_path)
    except Exception as exc:
        await execute(
            "UPDATE local_backup_pushes SET status='failed', error=$2 WHERE id=$1",
            push_row["id"], str(exc),
        )
        raise

    # Retourne le push à jour
    pushes = await list_pushes(backup_id)
    return next(p for p in pushes if p.remote_connection_id == remote_id)


async def _provider_for(remote_id: UUID):
    """Résout la connection + credentials + instancie le provider."""
    from agflow.services.remote_backup_connections_service import _fetch_row_by_id
    from agflow.services.remote_backup_providers.factory import get_provider
    from agflow.services import vault_client

    conn_row = await _fetch_row_by_id(remote_id)
    if conn_row is None:
        raise LookupError(f"remote_backup_connection not found: {remote_id}")

    config = conn_row["config"]
    if isinstance(config, str):
        import json
        config = json.loads(config)

    credentials: dict = {}
    if conn_row.get("vault_secret_path"):
        secret = await vault_client.get_secret(conn_row["vault_secret_path"])
        credentials = {"secret": secret}

    return get_provider(conn_row["kind"], config, credentials)


async def _push_to_remote(
    *, backup_id: UUID, provider, local_file_path: str, filename: str
) -> tuple[str, int]:
    """Réalise l'upload via provider.upload_stream. Retourne (remote_path, size_bytes)."""
    async def _file_chunks():
        # Lire le fichier local par chunks de 64KB
        path = Path(local_file_path)
        with path.open("rb") as f:
            while chunk := f.read(65536):
                yield chunk

    remote_path = f"full/{filename}"
    size_bytes = await provider.upload_stream(remote_path, filename, _file_chunks())
    return remote_path, size_bytes
```

- [ ] **Step 4 : Run tests, doivent passer**

```bash
cd backend && uv run pytest tests/services/test_local_backup_pushes_service.py -v
```

Expected : 8 PASS (DB ok) ou DONE_WITH_CONCERNS.

- [ ] **Step 5 : Lint + ligne count**

```bash
cd backend && uv run ruff check src/agflow/services/local_backup_pushes_service.py tests/services/test_local_backup_pushes_service.py
wc -l backend/src/agflow/services/local_backup_pushes_service.py
```

Expected : clean + < 300 lignes.

- [ ] **Step 6 : Commit**

```bash
git add backend/src/agflow/services/local_backup_pushes_service.py backend/tests/services/test_local_backup_pushes_service.py
git commit -m "feat(backup-services): local_backup_pushes_service (seed + push_all + push_one + exceptions)"
```

### Task 5 : `local_backups_service.delete_file_only` + prune adapté

**Files:**
- Modify: `backend/src/agflow/services/local_backups_service.py`

- [ ] **Step 1 : Ajouter `delete_file_only`**

Lire le fichier existant pour trouver la fonction `delete_backup` (qui supprime row + fichier). Ajouter à côté :

```python
async def delete_file_only(backup_id: UUID) -> None:
    """Supprime le fichier .dump localement, UPDATE local_file_present=false.
    La row local_backups est PRÉSERVÉE (audit + push history)."""
    row = await fetch_one(
        "SELECT file_path, local_file_present FROM local_backups WHERE id = $1",
        backup_id,
    )
    if row is None:
        raise BackupNotFoundError(str(backup_id))
    if not row["local_file_present"]:
        return  # idempotent

    file_path = Path(row["file_path"])
    try:
        file_path.unlink(missing_ok=True)
    except OSError as exc:
        log.warning("local_backup.delete_file_failed",
                    backup_id=str(backup_id), file_path=str(file_path), error=str(exc))

    await execute(
        "UPDATE local_backups SET local_file_present=false WHERE id=$1", backup_id
    )
    log.info("local_backup.file_deleted", backup_id=str(backup_id))
```

- [ ] **Step 2 : Modifier `prune_old_backups`** pour skip les rows déjà sans fichier

Trouver la fonction `prune_old_backups` (ou équivalent qui supprime les vieux backups). La requête SELECT pour identifier les anciens doit ajouter `AND local_file_present = true` pour ne pas re-supprimer ce qui n'a déjà plus de fichier.

Cible :
```python
# Dans la query SELECT des candidats à supprimer :
rows = await fetch_all(
    "SELECT id, file_path FROM local_backups "
    "WHERE source_schedule_full_id = $1 AND local_file_present = true "
    "ORDER BY created_at DESC OFFSET $2",
    schedule_id, retention_count,
)
```

- [ ] **Step 3 : Vérifier import + lint**

```bash
cd backend && uv run python -c "from agflow.services.local_backups_service import delete_file_only; print('ok')"
cd backend && uv run ruff check src/agflow/services/local_backups_service.py
```

- [ ] **Step 4 : Commit**

```bash
git add backend/src/agflow/services/local_backups_service.py
git commit -m "feat(backup-services): local_backups_service.delete_file_only + prune skip rows sans fichier"
```

---

## LOT 2 — Job runner + API (P2)

### Task 6 : Refactor `backup_job_runner.run_full_job`

**Files:**
- Modify: `backend/src/agflow/services/backup_job_runner.py`
- Modify: `backend/tests/services/test_backup_job_runner.py`

- [ ] **Step 1 : Adapter `run_full_job`**

Lire `backup_job_runner.py`. Trouver `run_full_job(schedule_id)`. Remplacer la logique de push mono-remote par le pattern multi-remote :

```python
async def run_full_job(schedule_id: UUID) -> None:
    """Cycle de vie d'un job 'full' :
    1. Lit le schedule (si disabled → no-op)
    2. Crée le local_backup (mandatory — source des pushes)
    3. Si remote_connection_ids : seed pushes 'pending' + push_all_pending
    4. Si keep_local=false ET tous pushes ok : delete_file_only
    5. record_run + prune_old_backups
    """
    schedule = await backup_schedules_service.get_full_schedule(schedule_id)
    if not schedule.enabled:
        log.info("backup_job.skip_disabled", schedule_id=str(schedule_id))
        return

    try:
        # 1) Création du backup local
        backup = await local_backups_service.create_backup(
            source_schedule_full_id=schedule_id,
        )

        # 2) Pushes
        all_pushes_ok = True
        if schedule.remote_connection_ids:
            await local_backup_pushes_service.seed_pushes(
                backup_id=backup.id,
                remote_ids=schedule.remote_connection_ids,
            )
            all_pushes_ok = await local_backup_pushes_service.push_all_pending(
                backup_id=backup.id
            )

        # 3) Suppression fichier si keep_local=false ET tous pushes ok
        if not schedule.keep_local and all_pushes_ok:
            await local_backups_service.delete_file_only(backup.id)

        # 4) Record run
        status = "ok" if (all_pushes_ok or not schedule.remote_connection_ids) else "ok"
        # On considère "ok" même avec push partiel — l'admin voit les ✗ sur le local_backup.
        # status='failed' uniquement si la création du backup local échoue (exception remontée plus bas).
        await backup_schedules_service.record_run(
            schedule_id=schedule_id, status=status
        )

        # 5) Prune
        await backup_schedules_service.prune_old_backups(
            schedule_id, schedule.retention_count
        )

    except Exception as exc:
        log.error("backup_job.failed", schedule_id=str(schedule_id), error=str(exc))
        await backup_schedules_service.record_run(
            schedule_id=schedule_id, status="failed", error=str(exc)
        )
        raise
```

Imports à ajouter en haut du fichier :
```python
from agflow.services import (
    backup_schedules_service,
    local_backup_pushes_service,
    local_backups_service,
)
```

- [ ] **Step 2 : Adapter les tests existants**

Lire `tests/services/test_backup_job_runner.py`. Remplacer les mocks/asserts qui parlaient de `remote_connection_id` par les nouveaux mocks `seed_pushes` + `push_all_pending`.

Ajouter les tests :

```python
async def test_run_full_job_multi_remote_happy_path():
    """schedule avec 2 remotes → seed_pushes + push_all_pending OK → record_run('ok')."""
    from tests._db_reset import reset_schema_and_migrate
    from agflow.db.pool import fetch_one
    await reset_schema_and_migrate()

    r1 = (await fetch_one(
        "INSERT INTO remote_backup_connections (name, kind, config) "
        "VALUES ('r1', 'sftp', '{}'::jsonb) RETURNING id"
    ))["id"]
    r2 = (await fetch_one(
        "INSERT INTO remote_backup_connections (name, kind, config) "
        "VALUES ('r2', 'sftp', '{}'::jsonb) RETURNING id"
    ))["id"]

    sched = await backup_schedules_service.create_full_schedule(
        name="multi", cron_expr="0 3 * * *",
        remote_connection_ids=[r1, r2], keep_local=True,
        retention_count=10, enabled=True, actor_user_id=None,
    )

    with patch(
        "agflow.services.backup_job_runner.local_backups_service.create_backup",
        new=AsyncMock(return_value=type("B", (), {"id": uuid4()})()),
    ), patch(
        "agflow.services.backup_job_runner.local_backup_pushes_service.push_all_pending",
        new=AsyncMock(return_value=True),
    ) as mock_push_all, patch(
        "agflow.services.backup_job_runner.local_backup_pushes_service.seed_pushes",
        new=AsyncMock(),
    ) as mock_seed, patch(
        "agflow.services.backup_job_runner.local_backups_service.delete_file_only",
        new=AsyncMock(),
    ) as mock_delete:
        await backup_job_runner.run_full_job(sched.id)

    mock_seed.assert_called_once()
    mock_push_all.assert_called_once()
    mock_delete.assert_not_called()  # keep_local=true


async def test_run_full_job_keep_local_false_all_ok_deletes_file():
    """schedule avec keep_local=false + push_all OK → delete_file_only appelé."""
    from tests._db_reset import reset_schema_and_migrate
    from agflow.db.pool import fetch_one
    await reset_schema_and_migrate()

    r1 = (await fetch_one(
        "INSERT INTO remote_backup_connections (name, kind, config) "
        "VALUES ('r1', 'sftp', '{}'::jsonb) RETURNING id"
    ))["id"]
    sched = await backup_schedules_service.create_full_schedule(
        name="no-local", cron_expr="0 3 * * *",
        remote_connection_ids=[r1], keep_local=False,
        retention_count=10, enabled=True, actor_user_id=None,
    )

    backup_id = uuid4()
    with patch(
        "agflow.services.backup_job_runner.local_backups_service.create_backup",
        new=AsyncMock(return_value=type("B", (), {"id": backup_id})()),
    ), patch(
        "agflow.services.backup_job_runner.local_backup_pushes_service.push_all_pending",
        new=AsyncMock(return_value=True),
    ), patch(
        "agflow.services.backup_job_runner.local_backup_pushes_service.seed_pushes",
        new=AsyncMock(),
    ), patch(
        "agflow.services.backup_job_runner.local_backups_service.delete_file_only",
        new=AsyncMock(),
    ) as mock_delete:
        await backup_job_runner.run_full_job(sched.id)

    mock_delete.assert_called_once_with(backup_id)


async def test_run_full_job_keep_local_false_push_fail_keeps_file():
    """schedule avec keep_local=false + push_all FAIL → file NOT deleted."""
    from tests._db_reset import reset_schema_and_migrate
    from agflow.db.pool import fetch_one
    await reset_schema_and_migrate()

    r1 = (await fetch_one(
        "INSERT INTO remote_backup_connections (name, kind, config) "
        "VALUES ('r1', 'sftp', '{}'::jsonb) RETURNING id"
    ))["id"]
    sched = await backup_schedules_service.create_full_schedule(
        name="no-local-fail", cron_expr="0 3 * * *",
        remote_connection_ids=[r1], keep_local=False,
        retention_count=10, enabled=True, actor_user_id=None,
    )

    with patch(
        "agflow.services.backup_job_runner.local_backups_service.create_backup",
        new=AsyncMock(return_value=type("B", (), {"id": uuid4()})()),
    ), patch(
        "agflow.services.backup_job_runner.local_backup_pushes_service.push_all_pending",
        new=AsyncMock(return_value=False),  # partial fail
    ), patch(
        "agflow.services.backup_job_runner.local_backup_pushes_service.seed_pushes",
        new=AsyncMock(),
    ), patch(
        "agflow.services.backup_job_runner.local_backups_service.delete_file_only",
        new=AsyncMock(),
    ) as mock_delete:
        await backup_job_runner.run_full_job(sched.id)

    mock_delete.assert_not_called()  # file conservé en cas d'échec partiel
```

- [ ] **Step 3 : Run tests**

```bash
cd backend && uv run pytest tests/services/test_backup_job_runner.py -v
```

Expected : tous PASS (mocks couvrent l'I/O) ou DONE_WITH_CONCERNS sur les tests qui appellent `create_full_schedule` réel.

- [ ] **Step 4 : Lint + commit**

```bash
cd backend && uv run ruff check src/agflow/services/backup_job_runner.py tests/services/test_backup_job_runner.py
git add backend/src/agflow/services/backup_job_runner.py backend/tests/services/test_backup_job_runner.py
git commit -m "feat(backup-services): backup_job_runner multi-remote (seed pushes + push_all + keep_local)"
```

### Task 7 : Adapter l'API `/backup-schedules/full` (POST/PUT)

**Files:**
- Modify: `backend/src/agflow/api/admin/backup_schedules.py`
- Modify: `backend/tests/api/test_admin_backup_schedules.py`

- [ ] **Step 1 : Adapter le router**

Lire `backend/src/agflow/api/admin/backup_schedules.py`. Pour les handlers `create_full`, `update_full`, `list_full`, `get_full` :
- Le payload Pydantic est déjà adapté (Task 2)
- Le service est déjà adapté (Task 3)
- Le handler doit catcher la nouvelle exception `EmptyDestinationsError` → 422

Cible pour `create_full` :
```python
@router.post("/full", response_model=FullScheduleSummary, status_code=201)
async def create_full(
    payload: CreateFullPayload, actor_user_id: str = Depends(require_admin)
) -> FullScheduleSummary:
    try:
        actor_uuid = UUID(actor_user_id) if actor_user_id else None
    except ValueError:
        actor_uuid = None
    try:
        return await backup_schedules_service.create_full_schedule(
            name=payload.name,
            cron_expr=payload.cron_expr,
            remote_connection_ids=payload.remote_connection_ids,
            keep_local=payload.keep_local,
            retention_count=payload.retention_count,
            enabled=payload.enabled,
            actor_user_id=actor_uuid,
        )
    except backup_schedules_service.InvalidCronError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except backup_schedules_service.EmptyDestinationsError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except backup_schedules_service.RemoteNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"remote not found: {exc}") from exc
```

Idem pour `update_full` avec le même bloc try/except.

- [ ] **Step 2 : Adapter les tests existants**

Adapter `tests/api/test_admin_backup_schedules.py` : tous les payloads JSON doivent envoyer `remote_connection_ids: [...]` au lieu de `remote_connection_id: ...` et ajouter `keep_local: true/false`.

Ajouter :
```python
def test_post_full_422_empty_destinations(client: TestClient):
    """POST avec keep_local=false + remote_connection_ids=[] → 422."""
    with patch(
        "agflow.api.admin.backup_schedules.backup_schedules_service.create_full_schedule",
        new=AsyncMock(side_effect=backup_schedules_service.EmptyDestinationsError("no dest")),
    ):
        r = client.post(
            "/api/admin/backup-schedules/full",
            headers=_auth(_admin_token()),
            json={
                "name": "bad",
                "cron_expr": "0 3 * * *",
                "remote_connection_ids": [],
                "keep_local": False,
                "retention_count": 10,
                "enabled": True,
            },
        )
    assert r.status_code == 422


def test_post_full_404_unknown_remote(client: TestClient):
    with patch(
        "agflow.api.admin.backup_schedules.backup_schedules_service.create_full_schedule",
        new=AsyncMock(side_effect=backup_schedules_service.RemoteNotFoundError("unknown-uuid")),
    ):
        r = client.post(
            "/api/admin/backup-schedules/full",
            headers=_auth(_admin_token()),
            json={
                "name": "s",
                "cron_expr": "0 3 * * *",
                "remote_connection_ids": ["12345678-1234-1234-1234-123456789abc"],
                "keep_local": True,
                "retention_count": 10,
                "enabled": True,
            },
        )
    assert r.status_code == 404
```

- [ ] **Step 3 : Run tests**

```bash
cd backend && uv run pytest tests/api/test_admin_backup_schedules.py -v
```

Expected : tous PASS (mocks → no DB).

- [ ] **Step 4 : Lint + commit**

```bash
cd backend && uv run ruff check src/agflow/api/admin/backup_schedules.py tests/api/test_admin_backup_schedules.py
git add backend/src/agflow/api/admin/backup_schedules.py backend/tests/api/test_admin_backup_schedules.py
git commit -m "feat(backup-api): backup_schedules POST/PUT acceptent remote_connection_ids + keep_local (+ 422/404)"
```

### Task 8 : 2 nouveaux endpoints sur `/local-backups`

**Files:**
- Modify: `backend/src/agflow/api/admin/local_backups.py`
- Modify: `backend/tests/api/test_admin_local_backups.py`

- [ ] **Step 1 : Ajouter les endpoints**

Append à `backend/src/agflow/api/admin/local_backups.py` :

```python
from uuid import UUID
from agflow.schemas.local_backup_pushes import LocalBackupPushSummary
from agflow.services import local_backup_pushes_service


@router.get("/{backup_id}/pushes", response_model=list[LocalBackupPushSummary])
async def list_pushes(backup_id: UUID) -> list[LocalBackupPushSummary]:
    """Liste les pushes (1 par remote configurée) d'un local_backup."""
    return await local_backup_pushes_service.list_pushes(backup_id)


@router.post("/{backup_id}/push/{remote_id}", status_code=202)
async def push_backup(backup_id: UUID, remote_id: UUID) -> dict[str, str]:
    """Re-push manuel d'un local_backup vers une remote (utile si push initial échoué)."""
    try:
        result = await local_backup_pushes_service.push_one(
            backup_id=backup_id, remote_id=remote_id
        )
    except local_backup_pushes_service.PushNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"push not found: {exc}") from exc
    except local_backup_pushes_service.LocalFileMissingError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"local file missing: {exc}",
        ) from exc
    return {"status": result.status}
```

- [ ] **Step 2 : Modifier GET `/local-backups` pour inclure les pushes**

Trouver la fonction qui retourne la liste des local_backups. Ajouter au DTO (ou au mapper) un champ `pushes` agrégé. Modifier le SQL pour LEFT JOIN + json_agg, **OU** appeler `local_backup_pushes_service.list_pushes(b.id)` pour chaque backup (N+1 acceptable pour les volumes attendus < 100 backups affichés).

Variante simple (N+1) :
```python
async def list_local_backups() -> list[LocalBackupSummary]:
    backups = await fetch_all("SELECT ... FROM local_backups ORDER BY created_at DESC")
    result = []
    for b in backups:
        pushes = await local_backup_pushes_service.list_pushes(b["id"])
        result.append(LocalBackupSummary(**b, pushes=pushes))
    return result
```

Variante optimale (LEFT JOIN avec json_agg) :
```sql
SELECT lb.*,
       coalesce(
         json_agg(
           json_build_object(
             'id', p.id,
             'local_backup_id', p.local_backup_id,
             'remote_connection_id', p.remote_connection_id,
             'remote_connection_name', r.name,
             'status', p.status,
             'pushed_at', p.pushed_at,
             'error', p.error,
             'remote_path', p.remote_path,
             'size_bytes', p.size_bytes,
             'created_at', p.created_at,
             'updated_at', p.updated_at
           )
         ) FILTER (WHERE p.id IS NOT NULL),
         '[]'::json
       ) AS pushes
FROM local_backups lb
LEFT JOIN local_backup_pushes p ON p.local_backup_id = lb.id
LEFT JOIN remote_backup_connections r ON r.id = p.remote_connection_id
GROUP BY lb.id
ORDER BY lb.created_at DESC
```

Choisir la variante optimale si la requête reste lisible.

Adapter le DTO `LocalBackupSummary` dans `backend/src/agflow/schemas/local_backups.py` :
```python
class LocalBackupSummary(BaseModel):
    # ... champs existants
    local_file_present: bool                          # ← nouveau
    pushes: list[LocalBackupPushSummary] = []         # ← nouveau
```

- [ ] **Step 3 : Tests**

Ajouter dans `tests/api/test_admin_local_backups.py` :

```python
def test_get_pushes_returns_list(client: TestClient):
    from agflow.schemas.local_backup_pushes import LocalBackupPushSummary
    from datetime import UTC, datetime
    fake_pushes = [
        LocalBackupPushSummary(
            id=uuid4(), local_backup_id=uuid4(), remote_connection_id=uuid4(),
            remote_connection_name="r1", status="ok", pushed_at=datetime.now(UTC),
            error=None, remote_path="full/x.dump", size_bytes=1024,
            created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        )
    ]
    with patch(
        "agflow.api.admin.local_backups.local_backup_pushes_service.list_pushes",
        new=AsyncMock(return_value=fake_pushes),
    ):
        r = client.get(
            f"/api/admin/local-backups/{uuid4()}/pushes",
            headers=_auth(_admin_token()),
        )
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["status"] == "ok"


def test_post_push_202(client: TestClient):
    from agflow.schemas.local_backup_pushes import LocalBackupPushSummary
    from datetime import UTC, datetime
    fake_result = LocalBackupPushSummary(
        id=uuid4(), local_backup_id=uuid4(), remote_connection_id=uuid4(),
        remote_connection_name="r1", status="ok", pushed_at=datetime.now(UTC),
        error=None, remote_path="full/x.dump", size_bytes=1024,
        created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
    )
    with patch(
        "agflow.api.admin.local_backups.local_backup_pushes_service.push_one",
        new=AsyncMock(return_value=fake_result),
    ):
        r = client.post(
            f"/api/admin/local-backups/{uuid4()}/push/{uuid4()}",
            headers=_auth(_admin_token()),
        )
    assert r.status_code == 202
    assert r.json() == {"status": "ok"}


def test_post_push_404_push_not_found(client: TestClient):
    with patch(
        "agflow.api.admin.local_backups.local_backup_pushes_service.push_one",
        new=AsyncMock(side_effect=local_backup_pushes_service.PushNotFoundError("nope")),
    ):
        r = client.post(
            f"/api/admin/local-backups/{uuid4()}/push/{uuid4()}",
            headers=_auth(_admin_token()),
        )
    assert r.status_code == 404


def test_post_push_409_local_file_missing(client: TestClient):
    with patch(
        "agflow.api.admin.local_backups.local_backup_pushes_service.push_one",
        new=AsyncMock(side_effect=local_backup_pushes_service.LocalFileMissingError("file gone")),
    ):
        r = client.post(
            f"/api/admin/local-backups/{uuid4()}/push/{uuid4()}",
            headers=_auth(_admin_token()),
        )
    assert r.status_code == 409
```

- [ ] **Step 4 : Run tests**

```bash
cd backend && uv run pytest tests/api/test_admin_local_backups.py -v
```

Expected : tous PASS (mocks).

- [ ] **Step 5 : Lint + commit**

```bash
cd backend && uv run ruff check src/agflow/api/admin/local_backups.py src/agflow/schemas/local_backups.py tests/api/test_admin_local_backups.py
git add backend/src/agflow/api/admin/local_backups.py backend/src/agflow/schemas/local_backups.py backend/tests/api/test_admin_local_backups.py
git commit -m "feat(backup-api): GET /local-backups/{id}/pushes + POST .../push/{remote_id} + pushes dans GET list"
```

---

## LOT 3 — Wizard frontend (P3)

### Task 9 : Helpers cron (build / parse / format) + tests

**Files:**
- Create: `frontend/src/lib/cronWizard.ts`
- Create: `frontend/src/lib/cronWizard.test.ts`

- [ ] **Step 1 : Écrire les tests (TDD red)**

```typescript
// frontend/src/lib/cronWizard.test.ts
import { describe, it, expect } from "vitest";

import { buildCron, formatCronHuman, parseCron } from "./cronWizard";

describe("buildCron", () => {
  it("hourly at minute 15 → '15 * * * *'", () => {
    expect(buildCron("hourly", 15)).toBe("15 * * * *");
  });
  it("daily at hour 3 → '0 3 * * *'", () => {
    expect(buildCron("daily", 3)).toBe("0 3 * * *");
  });
});

describe("parseCron", () => {
  it("'15 * * * *' → hourly at minute 15", () => {
    expect(parseCron("15 * * * *")).toEqual({ recurrence: "hourly", offset: 15 });
  });
  it("'0 3 * * *' → daily at hour 3", () => {
    expect(parseCron("0 3 * * *")).toEqual({ recurrence: "daily", offset: 3 });
  });
  it("'0 0 * * *' → daily at hour 0 (midnight)", () => {
    expect(parseCron("0 0 * * *")).toEqual({ recurrence: "daily", offset: 0 });
  });
  it("'*/15 * * * *' → null (cron complexe)", () => {
    expect(parseCron("*/15 * * * *")).toBeNull();
  });
  it("'0 3 * * 1' → null (jour de semaine spécifié)", () => {
    expect(parseCron("0 3 * * 1")).toBeNull();
  });
  it("'invalid' → null", () => {
    expect(parseCron("invalid")).toBeNull();
  });
});

describe("formatCronHuman", () => {
  it("'15 * * * *' → 'Toutes les heures à xx:15'", () => {
    expect(formatCronHuman("15 * * * *")).toBe("Toutes les heures à xx:15");
  });
  it("'0 3 * * *' → 'Tous les jours à 03:00'", () => {
    expect(formatCronHuman("0 3 * * *")).toBe("Tous les jours à 03:00");
  });
  it("cron complexe → renvoie le cron brut", () => {
    expect(formatCronHuman("*/15 * * * *")).toBe("*/15 * * * *");
  });
});
```

- [ ] **Step 2 : Run, échoue (module absent)**

```bash
cd frontend && npm test -- --run cronWizard
```

Expected : FAIL (module not found).

- [ ] **Step 3 : Écrire le module**

```typescript
// frontend/src/lib/cronWizard.ts
export type RecurrenceType = "hourly" | "daily";

export function buildCron(recurrence: RecurrenceType, offset: number): string {
  if (recurrence === "hourly") return `${offset} * * * *`;
  return `0 ${offset} * * *`;
}

export function parseCron(
  cron: string,
): { recurrence: RecurrenceType; offset: number } | null {
  const parts = cron.trim().split(/\s+/);
  if (parts.length !== 5) return null;
  const [min, hr, dom, mon, dow] = parts;

  // "M * * * *" → hourly at minute M
  if (
    hr === "*" &&
    dom === "*" &&
    mon === "*" &&
    dow === "*" &&
    /^\d+$/.test(min)
  ) {
    const n = parseInt(min, 10);
    if (n >= 0 && n <= 59) return { recurrence: "hourly", offset: n };
  }

  // "0 H * * *" → daily at hour H
  if (
    min === "0" &&
    dom === "*" &&
    mon === "*" &&
    dow === "*" &&
    /^\d+$/.test(hr)
  ) {
    const n = parseInt(hr, 10);
    if (n >= 0 && n <= 23) return { recurrence: "daily", offset: n };
  }

  return null;
}

export function formatCronHuman(cron: string): string {
  const parsed = parseCron(cron);
  if (parsed === null) return cron; // fallback : afficher le cron brut

  if (parsed.recurrence === "hourly") {
    const mm = String(parsed.offset).padStart(2, "0");
    return `Toutes les heures à xx:${mm}`;
  }
  const hh = String(parsed.offset).padStart(2, "0");
  return `Tous les jours à ${hh}:00`;
}
```

- [ ] **Step 4 : Run tests, passent**

```bash
cd frontend && npm test -- --run cronWizard
```

Expected : 11 PASS.

- [ ] **Step 5 : tsc**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 6 : Commit**

```bash
git add frontend/src/lib/cronWizard.ts frontend/src/lib/cronWizard.test.ts
git commit -m "feat(backup-ui): cronWizard helpers (buildCron + parseCron + formatCronHuman) + tests"
```

### Task 10 : Composant `ScheduleWizard.tsx` + tests

**Files:**
- Create: `frontend/src/components/backups/ScheduleWizard.tsx`
- Create: `frontend/src/components/backups/__tests__/ScheduleWizard.test.tsx`
- Modify: `frontend/src/lib/backupSchedulesApi.ts`

- [ ] **Step 1 : Adapter `backupSchedulesApi.ts`**

Remplacer dans `FullScheduleSummary`, `CreateFullPayload`, `UpdateFullPayload` :
- `remote_connection_id: string | null` → `remote_connection_ids: string[]`
- Ajouter `keep_local: boolean`

Exemple cible :
```typescript
export interface FullScheduleSummary {
  id: string;
  name: string;
  cron_expr: string;
  remote_connection_ids: string[];
  keep_local: boolean;
  retention_count: number;
  enabled: boolean;
  last_run_at: string | null;
  last_run_status: "ok" | "failed" | null;
  last_run_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface CreateFullPayload {
  name: string;
  cron_expr: string;
  remote_connection_ids: string[];
  keep_local: boolean;
  retention_count?: number;
  enabled?: boolean;
}

export interface UpdateFullPayload {
  name?: string;
  cron_expr?: string;
  remote_connection_ids?: string[];
  keep_local?: boolean;
  retention_count?: number;
  enabled?: boolean;
}
```

- [ ] **Step 2 : Écrire le composant `ScheduleWizard.tsx`**

```tsx
// frontend/src/components/backups/ScheduleWizard.tsx
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import {
  type FullScheduleSummary,
  type CreateFullPayload,
} from "@/lib/backupSchedulesApi";
import { buildCron, parseCron, type RecurrenceType } from "@/lib/cronWizard";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

interface Connection {
  id: string;
  name: string;
  kind: string;
}

export interface ScheduleWizardProps {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  mode: "create" | "edit";
  initialSchedule?: FullScheduleSummary;
  onSubmit: (payload: CreateFullPayload) => Promise<void>;
}

export function ScheduleWizard({
  open,
  onOpenChange,
  mode,
  initialSchedule,
  onSubmit,
}: ScheduleWizardProps) {
  const { t } = useTranslation();
  const remotesQuery = useQuery<Connection[]>({
    queryKey: ["backup-remotes"],
    queryFn: () => api.get<Connection[]>("/admin/backup-remotes").then((r) => r.data),
  });

  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [recurrence, setRecurrence] = useState<RecurrenceType | null>(null);
  const [offset, setOffset] = useState<number | null>(null);
  const [name, setName] = useState("");
  const [keepLocal, setKeepLocal] = useState(true);
  const [remoteConnectionIds, setRemoteConnectionIds] = useState<string[]>([]);
  const [retentionCount, setRetentionCount] = useState(10);
  const [cronFallback, setCronFallback] = useState<string | null>(null);

  useEffect(() => {
    if (mode === "edit" && initialSchedule) {
      setName(initialSchedule.name);
      setKeepLocal(initialSchedule.keep_local);
      setRemoteConnectionIds(initialSchedule.remote_connection_ids);
      setRetentionCount(initialSchedule.retention_count);
      const parsed = parseCron(initialSchedule.cron_expr);
      if (parsed) {
        setRecurrence(parsed.recurrence);
        setOffset(parsed.offset);
        setCronFallback(null);
      } else {
        setCronFallback(initialSchedule.cron_expr);
      }
    } else if (mode === "create" && open) {
      // Reset pour création
      setStep(1);
      setRecurrence(null);
      setOffset(null);
      setName("");
      setKeepLocal(true);
      setRemoteConnectionIds([]);
      setRetentionCount(10);
      setCronFallback(null);
    }
  }, [mode, initialSchedule, open]);

  const canGoStep2 = recurrence !== null;
  const offsetMax = recurrence === "hourly" ? 59 : 23;
  const canGoStep3 = offset !== null && offset >= 0 && offset <= offsetMax;
  const hasDestination = keepLocal || remoteConnectionIds.length > 0;
  const canSubmit = name.trim().length > 0 && hasDestination;

  const toggleRemote = (id: string) => {
    setRemoteConnectionIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  };

  const handleSubmit = async () => {
    if (!canSubmit) return;
    const cron = cronFallback ?? buildCron(recurrence!, offset!);
    await onSubmit({
      name,
      cron_expr: cron,
      remote_connection_ids: remoteConnectionIds,
      keep_local: keepLocal,
      retention_count: retentionCount,
      enabled: true,
    });
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {mode === "create"
              ? t("backups.wizard.title_create")
              : t("backups.wizard.title_edit")}
          </DialogTitle>
          <p className="text-xs text-muted-foreground">
            {t("backups.wizard.step_label", { current: step, total: 3 })}
          </p>
        </DialogHeader>

        {cronFallback ? (
          <div className="space-y-2">
            <p className="text-sm text-muted-foreground">
              {t("backups.wizard.complexCron")} :{" "}
              <code className="font-mono">{cronFallback}</code>
            </p>
            <Label>{t("backups.wizard.editRaw")}</Label>
            <Input value={cronFallback} onChange={(e) => setCronFallback(e.target.value)} />
          </div>
        ) : (
          <>
            {step === 1 && (
              <div className="space-y-2">
                <Label>{t("backups.wizard.step1.title")}</Label>
                <label className="flex items-center gap-2">
                  <input
                    type="radio"
                    checked={recurrence === "hourly"}
                    onChange={() => setRecurrence("hourly")}
                  />
                  {t("backups.wizard.step1.hourly")}
                </label>
                <label className="flex items-center gap-2">
                  <input
                    type="radio"
                    checked={recurrence === "daily"}
                    onChange={() => setRecurrence("daily")}
                  />
                  {t("backups.wizard.step1.daily")}
                </label>
              </div>
            )}

            {step === 2 && (
              <div className="space-y-2">
                <Label>
                  {recurrence === "hourly"
                    ? t("backups.wizard.step2.atMinute")
                    : t("backups.wizard.step2.atHour")}
                </Label>
                <Input
                  type="number"
                  min={0}
                  max={offsetMax}
                  value={offset ?? ""}
                  onChange={(e) =>
                    setOffset(e.target.value === "" ? null : parseInt(e.target.value, 10))
                  }
                />
                <p className="text-xs text-muted-foreground">
                  {recurrence === "hourly"
                    ? t("backups.wizard.step2.minuteHint")
                    : t("backups.wizard.step2.hourHint")}
                </p>
              </div>
            )}

            {step === 3 && (
              <div className="space-y-3">
                <div className="space-y-1">
                  <Label htmlFor="wizard-name">{t("backups.wizard.step3.name")}</Label>
                  <Input
                    id="wizard-name"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder={t("backups.wizard.step3.namePlaceholder")}
                  />
                </div>

                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={keepLocal}
                    onChange={(e) => setKeepLocal(e.target.checked)}
                  />
                  {t("backups.wizard.step3.keepLocal")}
                </label>

                <div className="space-y-1">
                  <Label>{t("backups.wizard.step3.remotes")}</Label>
                  <div className="max-h-40 space-y-1 overflow-y-auto rounded border p-2">
                    {remotesQuery.data?.length === 0 ? (
                      <p className="text-xs text-muted-foreground">
                        {t("backups.wizard.step3.noRemotes")}
                      </p>
                    ) : (
                      remotesQuery.data?.map((r) => (
                        <label key={r.id} className="flex items-center gap-2 text-sm">
                          <input
                            type="checkbox"
                            checked={remoteConnectionIds.includes(r.id)}
                            onChange={() => toggleRemote(r.id)}
                          />
                          {r.name}{" "}
                          <span className="text-xs text-muted-foreground">({r.kind})</span>
                        </label>
                      ))
                    )}
                  </div>
                </div>

                <div className="space-y-1">
                  <Label htmlFor="wizard-retention">
                    {t("backups.wizard.step3.retention")}
                  </Label>
                  <Input
                    id="wizard-retention"
                    type="number"
                    min={1}
                    value={retentionCount}
                    onChange={(e) =>
                      setRetentionCount(Math.max(1, parseInt(e.target.value, 10) || 1))
                    }
                  />
                </div>

                {!hasDestination && (
                  <p className="text-xs text-destructive">
                    {t("backups.wizard.step3.errorNoDestination")}
                  </p>
                )}
              </div>
            )}
          </>
        )}

        <DialogFooter>
          {step > 1 && !cronFallback && (
            <Button variant="ghost" onClick={() => setStep((s) => (s - 1) as 1 | 2 | 3)}>
              {t("backups.wizard.prev")}
            </Button>
          )}
          {step === 1 && !cronFallback && (
            <Button disabled={!canGoStep2} onClick={() => setStep(2)}>
              {t("backups.wizard.next")}
            </Button>
          )}
          {step === 2 && !cronFallback && (
            <Button disabled={!canGoStep3} onClick={() => setStep(3)}>
              {t("backups.wizard.next")}
            </Button>
          )}
          {(step === 3 || cronFallback) && (
            <Button disabled={!canSubmit} onClick={handleSubmit}>
              {t("backups.wizard.save")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 3 : Tests Vitest**

```tsx
// frontend/src/components/backups/__tests__/ScheduleWizard.test.tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

import { ScheduleWizard } from "../ScheduleWizard";
import { api } from "@/lib/api";

vi.mock("@/lib/api");

function wrap(node: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

describe("ScheduleWizard", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    (api.get as any).mockResolvedValue({
      data: [{ id: "r1", name: "s3-prod", kind: "s3" }],
    });
  });

  it("Step 1 → 2 disabled si pas de recurrence sélectionnée", () => {
    wrap(
      <ScheduleWizard
        open
        onOpenChange={() => {}}
        mode="create"
        onSubmit={async () => {}}
      />,
    );
    const nextBtn = screen.getByRole("button", { name: /suivant/i });
    expect(nextBtn).toBeDisabled();
  });

  it("Step 1 → 2 activé après choix recurrence", () => {
    wrap(
      <ScheduleWizard
        open
        onOpenChange={() => {}}
        mode="create"
        onSubmit={async () => {}}
      />,
    );
    fireEvent.click(screen.getByLabelText(/toutes les heures/i));
    expect(screen.getByRole("button", { name: /suivant/i })).not.toBeDisabled();
  });

  it("Step 2 affiche 'À la minute' si hourly choisi", () => {
    wrap(
      <ScheduleWizard
        open
        onOpenChange={() => {}}
        mode="create"
        onSubmit={async () => {}}
      />,
    );
    fireEvent.click(screen.getByLabelText(/toutes les heures/i));
    fireEvent.click(screen.getByRole("button", { name: /suivant/i }));
    expect(screen.getByLabelText(/à la minute/i)).toBeInTheDocument();
  });

  it("Step 3 bouton Save disabled si pas de destination", async () => {
    wrap(
      <ScheduleWizard
        open
        onOpenChange={() => {}}
        mode="create"
        onSubmit={async () => {}}
      />,
    );
    fireEvent.click(screen.getByLabelText(/tous les jours/i));
    fireEvent.click(screen.getByRole("button", { name: /suivant/i }));
    fireEvent.change(screen.getByLabelText(/à l'heure/i), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: /suivant/i }));
    await waitFor(() => screen.getByLabelText(/nom/i));
    fireEvent.change(screen.getByLabelText(/nom/i), { target: { value: "test" } });
    // Décocher local + aucune remote sélectionnée
    fireEvent.click(screen.getByLabelText(/conserver une copie locale/i));
    const saveBtn = screen.getByRole("button", { name: /enregistrer/i });
    expect(saveBtn).toBeDisabled();
  });

  it("Step 3 submit avec cron daily généré correctement", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    wrap(
      <ScheduleWizard
        open
        onOpenChange={() => {}}
        mode="create"
        onSubmit={onSubmit}
      />,
    );
    fireEvent.click(screen.getByLabelText(/tous les jours/i));
    fireEvent.click(screen.getByRole("button", { name: /suivant/i }));
    fireEvent.change(screen.getByLabelText(/à l'heure/i), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: /suivant/i }));
    await waitFor(() => screen.getByLabelText(/nom/i));
    fireEvent.change(screen.getByLabelText(/nom/i), { target: { value: "db-jour" } });
    fireEvent.click(screen.getByRole("button", { name: /enregistrer/i }));
    await waitFor(() =>
      expect(onSubmit).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "db-jour",
          cron_expr: "0 3 * * *",
          keep_local: true,
          remote_connection_ids: [],
        }),
      ),
    );
  });

  it("Mode edit pré-remplit depuis cron '15 * * * *'", () => {
    wrap(
      <ScheduleWizard
        open
        onOpenChange={() => {}}
        mode="edit"
        initialSchedule={{
          id: "s1",
          name: "db-horaire",
          cron_expr: "15 * * * *",
          remote_connection_ids: ["r1"],
          keep_local: true,
          retention_count: 24,
          enabled: true,
          last_run_at: null,
          last_run_status: null,
          last_run_error: null,
          created_at: "2026-05-20T00:00:00Z",
          updated_at: "2026-05-20T00:00:00Z",
        }}
        onSubmit={async () => {}}
      />,
    );
    // Le radio hourly doit être coché
    const hourlyRadio = screen.getByLabelText(/toutes les heures/i) as HTMLInputElement;
    expect(hourlyRadio.checked).toBe(true);
  });

  it("Mode edit cron complexe → fallback affiché", () => {
    wrap(
      <ScheduleWizard
        open
        onOpenChange={() => {}}
        mode="edit"
        initialSchedule={{
          id: "s1",
          name: "complex",
          cron_expr: "*/15 * * * *",
          remote_connection_ids: [],
          keep_local: true,
          retention_count: 10,
          enabled: true,
          last_run_at: null,
          last_run_status: null,
          last_run_error: null,
          created_at: "2026-05-20T00:00:00Z",
          updated_at: "2026-05-20T00:00:00Z",
        }}
        onSubmit={async () => {}}
      />,
    );
    expect(screen.getByText(/cron personnalisé|cron complexe/i)).toBeInTheDocument();
    expect(screen.getByDisplayValue("*/15 * * * *")).toBeInTheDocument();
  });
});
```

- [ ] **Step 4 : Run tests**

```bash
cd frontend && npm test -- --run ScheduleWizard
```

Expected : 7 PASS.

- [ ] **Step 5 : tsc**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 6 : Commit**

```bash
git add frontend/src/components/backups/ScheduleWizard.tsx frontend/src/components/backups/__tests__/ScheduleWizard.test.tsx frontend/src/lib/backupSchedulesApi.ts
git commit -m "feat(backup-ui): ScheduleWizard 3 steps (récurrence + moment + destinations) + tests"
```

### Task 11 : Intégrer le wizard dans `FullSchedulesSection`

**Files:**
- Modify: `frontend/src/components/backups/FullSchedulesSection.tsx`

- [ ] **Step 1 : Adapter le composant**

Lire le fichier existant. Remplacer le form mono-page par l'usage du wizard :

1. Importer `ScheduleWizard`, `formatCronHuman` :
   ```typescript
   import { ScheduleWizard } from "./ScheduleWizard";
   import { formatCronHuman } from "@/lib/cronWizard";
   ```

2. Ajouter un state pour le wizard :
   ```typescript
   const [wizardOpen, setWizardOpen] = useState(false);
   const [wizardMode, setWizardMode] = useState<"create" | "edit">("create");
   const [wizardSchedule, setWizardSchedule] = useState<FullScheduleSummary | undefined>();
   ```

3. Le bouton « + Ajouter » :
   ```tsx
   <Button onClick={() => { setWizardMode("create"); setWizardSchedule(undefined); setWizardOpen(true); }}>
     {t("backups.schedules.addFull")}
   </Button>
   ```

4. Le bouton « Édition » (icône pencil) sur chaque row :
   ```tsx
   <Button size="sm" variant="ghost" onClick={() => { setWizardMode("edit"); setWizardSchedule(s); setWizardOpen(true); }}>
     <Pencil className="w-3 h-3" />
   </Button>
   ```

5. La colonne « Cron » devient « Récurrence » :
   ```tsx
   <td>{formatCronHuman(s.cron_expr)}</td>
   ```

6. La colonne « Destination » :
   ```tsx
   <td className="space-x-2">
     {s.keep_local && <span title="local">✓ local</span>}
     {s.remote_connection_ids.map((rid) => {
       const r = connections.find((c) => c.id === rid);
       return <span key={rid}>· {r?.name ?? rid.slice(0, 8)}</span>;
     })}
     {!s.keep_local && s.remote_connection_ids.length === 0 && (
       <span className="text-muted-foreground">{t("backups.schedules.destinationLocalOnly")}</span>
     )}
   </td>
   ```

7. Le wizard en bas du composant :
   ```tsx
   <ScheduleWizard
     open={wizardOpen}
     onOpenChange={setWizardOpen}
     mode={wizardMode}
     initialSchedule={wizardSchedule}
     onSubmit={async (payload) => {
       if (wizardMode === "create") {
         await createMutation.mutateAsync(payload);
       } else if (wizardSchedule) {
         await updateMutation.mutateAsync({ id: wizardSchedule.id, payload });
       }
     }}
   />
   ```

8. **Retirer l'ancien form mono-page** (Sheet/Dialog avec les champs cron+remote unique + destination radio) qui est remplacé par le wizard.

- [ ] **Step 2 : tsc + visual smoke**

```bash
cd frontend && npx tsc --noEmit
```

Expected : 0 erreur. Visual smoke (ouvrir le dialog avec le wizard, vérifier qu'il s'affiche correctement) à faire au runtime après deploy.

- [ ] **Step 3 : Commit**

```bash
git add frontend/src/components/backups/FullSchedulesSection.tsx
git commit -m "feat(backup-ui): FullSchedulesSection utilise ScheduleWizard + colonne destinations multi-remote"
```

---

## LOT 4 — UI pushes + i18n (P4)

### Task 12 : `localBackupPushesApi.ts` (client TS)

**Files:**
- Create: `frontend/src/lib/localBackupPushesApi.ts`
- Modify: `frontend/src/lib/backupsApi.ts`

- [ ] **Step 1 : Créer le client TS**

```typescript
// frontend/src/lib/localBackupPushesApi.ts
import { api } from "./api";

export type PushStatus = "pending" | "pushing" | "ok" | "failed";

export interface LocalBackupPush {
  id: string;
  local_backup_id: string;
  remote_connection_id: string;
  remote_connection_name: string;
  status: PushStatus;
  pushed_at: string | null;
  error: string | null;
  remote_path: string | null;
  size_bytes: number | null;
  created_at: string;
  updated_at: string;
}

export const localBackupPushesApi = {
  listPushes: async (backupId: string): Promise<LocalBackupPush[]> =>
    (await api.get<LocalBackupPush[]>(`/admin/local-backups/${backupId}/pushes`)).data,
  pushBackup: async (backupId: string, remoteId: string): Promise<{ status: string }> =>
    (await api.post<{ status: string }>(`/admin/local-backups/${backupId}/push/${remoteId}`)).data,
};
```

- [ ] **Step 2 : Adapter `backupsApi.ts`**

Trouver l'interface `LocalBackup` (ou équivalent). Ajouter :
```typescript
import { type LocalBackupPush } from "./localBackupPushesApi";

export interface LocalBackup {
  // ... champs existants
  local_file_present: boolean;
  pushes: LocalBackupPush[];
}
```

- [ ] **Step 3 : Vérifier tsc + commit**

```bash
cd frontend && npx tsc --noEmit
git add frontend/src/lib/localBackupPushesApi.ts frontend/src/lib/backupsApi.ts
git commit -m "feat(backup-ui): localBackupPushesApi client + LocalBackup.pushes/local_file_present"
```

### Task 13 : Colonne « Pushes » dans `LocalBackupsSection`

**Files:**
- Modify: `frontend/src/components/backups/LocalBackupsSection.tsx`

- [ ] **Step 1 : Ajouter la colonne**

Lire `LocalBackupsSection.tsx`. Dans la table des local_backups, ajouter une nouvelle colonne « Pushes » :

```tsx
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { localBackupPushesApi } from "@/lib/localBackupPushesApi";
import { useMutation, useQueryClient } from "@tanstack/react-query";

// Dans le composant — fonction helper pour le badge
function pushBadge(status: string): string {
  if (status === "ok") return "✓";
  if (status === "failed") return "✗";
  if (status === "pushing") return "⏳";
  return "…";
}

// La mutation pour re-push
const qc = useQueryClient();
const pushMutation = useMutation({
  mutationFn: ({ backupId, remoteId }: { backupId: string; remoteId: string }) =>
    localBackupPushesApi.pushBackup(backupId, remoteId),
  onSuccess: () => qc.invalidateQueries({ queryKey: ["local-backups"] }),
});

// Dans le rendu de la table :
<thead>
  <tr>
    {/* ... colonnes existantes (filename, size, source, status) ... */}
    <th>{t("backups.pushes.title")}</th>
    {/* colonne actions */}
  </tr>
</thead>
<tbody>
  {data?.map((b) => (
    <tr key={b.id}>
      {/* ... cellules existantes ... */}
      <td className="space-x-2">
        {b.pushes.length === 0 ? (
          <span className="text-muted-foreground">—</span>
        ) : (
          b.pushes.map((p) => (
            <span
              key={p.remote_connection_id}
              title={p.error ?? p.status}
              className={p.status === "failed" ? "text-destructive" : ""}
            >
              {pushBadge(p.status)} {p.remote_connection_name}
            </span>
          ))
        )}
      </td>
      <td>
        {b.pushes.some((p) => p.status === "failed") && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button size="sm" variant="ghost">⋯</Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent>
              {b.pushes
                .filter((p) => p.status === "failed")
                .map((p) => (
                  <DropdownMenuItem
                    key={p.remote_connection_id}
                    onClick={() =>
                      pushMutation.mutate({
                        backupId: b.id,
                        remoteId: p.remote_connection_id,
                      })
                    }
                  >
                    {t("backups.pushes.rePushAction", { remote: p.remote_connection_name })}
                  </DropdownMenuItem>
                ))}
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </td>
    </tr>
  ))}
</tbody>
```

Note : si `local_file_present === false`, désactiver le bouton « Télécharger » du backup (colonne actions existante).

- [ ] **Step 2 : tsc + commit**

```bash
cd frontend && npx tsc --noEmit
git add frontend/src/components/backups/LocalBackupsSection.tsx
git commit -m "feat(backup-ui): colonne pushes dans LocalBackupsSection + menu re-push par remote échouée"
```

### Task 14 : i18n FR + EN

**Files:**
- Modify: `frontend/src/i18n/fr.json`
- Modify: `frontend/src/i18n/en.json`

- [ ] **Step 1 : Ajouter les clés FR**

Sous `backups`, ajouter ou compléter :

```json
{
  "backups": {
    "wizard": {
      "title_create": "Nouvelle planification",
      "title_edit": "Modifier la planification",
      "step_label": "Étape {{current}}/{{total}}",
      "next": "Suivant",
      "prev": "Précédent",
      "save": "Enregistrer",
      "complexCron": "Cron personnalisé",
      "editRaw": "Édition en cron brut",
      "step1": {
        "title": "Récurrence",
        "hourly": "Toutes les heures",
        "daily": "Tous les jours"
      },
      "step2": {
        "title": "Moment",
        "atMinute": "À la minute",
        "atHour": "À l'heure",
        "minuteHint": "Toutes les heures à xx:MM (0 à 59)",
        "hourHint": "Tous les jours à HH:00 (0 à 23)"
      },
      "step3": {
        "title": "Destinations",
        "name": "Nom de la planification",
        "namePlaceholder": "ex: db-quotidien",
        "keepLocal": "Conserver une copie locale",
        "remotes": "Destinations distantes",
        "noRemotes": "Aucune connexion distante configurée. Ajoutez-en une via Backup Remotes.",
        "retention": "Rétention (nombre de backups conservés)",
        "errorNoDestination": "Au moins une destination est requise (local OU au moins une remote)."
      }
    },
    "pushes": {
      "title": "Pushes",
      "statusOk": "OK",
      "statusFailed": "Échec",
      "statusPending": "En attente",
      "statusPushing": "Push en cours",
      "rePushAction": "Re-pousser vers {{remote}}",
      "rePushSuccess": "Push relancé",
      "rePushError": "Échec du re-push : {{error}}"
    },
    "schedules": {
      "destinationLocalOnly": "(local seul)"
    }
  }
}
```

- [ ] **Step 2 : Ajouter les clés EN équivalentes**

```json
{
  "backups": {
    "wizard": {
      "title_create": "New schedule",
      "title_edit": "Edit schedule",
      "step_label": "Step {{current}}/{{total}}",
      "next": "Next",
      "prev": "Previous",
      "save": "Save",
      "complexCron": "Custom cron",
      "editRaw": "Edit raw cron",
      "step1": {
        "title": "Recurrence",
        "hourly": "Every hour",
        "daily": "Every day"
      },
      "step2": {
        "title": "Moment",
        "atMinute": "At minute",
        "atHour": "At hour",
        "minuteHint": "Every hour at xx:MM (0 to 59)",
        "hourHint": "Every day at HH:00 (0 to 23)"
      },
      "step3": {
        "title": "Destinations",
        "name": "Schedule name",
        "namePlaceholder": "e.g. db-daily",
        "keepLocal": "Keep a local copy",
        "remotes": "Remote destinations",
        "noRemotes": "No remote connection configured. Add one via Backup Remotes.",
        "retention": "Retention (number of backups kept)",
        "errorNoDestination": "At least one destination required (local OR a remote)."
      }
    },
    "pushes": {
      "title": "Pushes",
      "statusOk": "OK",
      "statusFailed": "Failed",
      "statusPending": "Pending",
      "statusPushing": "Pushing",
      "rePushAction": "Re-push to {{remote}}",
      "rePushSuccess": "Push restarted",
      "rePushError": "Re-push failed: {{error}}"
    },
    "schedules": {
      "destinationLocalOnly": "(local only)"
    }
  }
}
```

- [ ] **Step 3 : Vérifier JSON valide**

```bash
node -e "JSON.parse(require('fs').readFileSync('frontend/src/i18n/fr.json','utf8'))"
node -e "JSON.parse(require('fs').readFileSync('frontend/src/i18n/en.json','utf8'))"
```

- [ ] **Step 4 : tsc + commit**

```bash
cd frontend && npx tsc --noEmit
git add frontend/src/i18n/fr.json frontend/src/i18n/en.json
git commit -m "feat(backup-ui): i18n FR + EN — clés wizard + pushes"
```

---

## LOT 5 — Validation (P5)

### Task 15 : Sanity check global

**Files:**
- (validation only)

- [ ] **Step 1 : Lint backend**

```bash
cd backend && uv run ruff check src/agflow/services/backup_schedules_service.py src/agflow/services/backup_job_runner.py src/agflow/services/local_backup_pushes_service.py src/agflow/services/local_backups_service.py src/agflow/api/admin/backup_schedules.py src/agflow/api/admin/local_backups.py src/agflow/schemas/backup_schedules.py src/agflow/schemas/local_backup_pushes.py
```

Expected : clean.

- [ ] **Step 2 : tsc frontend**

```bash
cd frontend && npx tsc --noEmit
```

Expected : 0 erreur.

- [ ] **Step 3 : Aucun reste de `remote_connection_id` mono-FK**

```bash
cd backend && grep -rn "remote_connection_id" src/agflow/services/backup_schedules_service.py src/agflow/services/backup_job_runner.py src/agflow/schemas/backup_schedules.py | grep -v "remote_connection_ids" | grep -v "schedule_full_remotes"
```

Expected : aucune sortie (toutes les références sont en multi-remote ou dans la join table).

- [ ] **Step 4 : Vérifier que `from agflow.main import create_app` fonctionne**

```bash
cd backend && uv run python -c "from agflow.main import create_app; print('ok')"
```

Expected : `ok`.

- [ ] **Step 5 : Pas de commit si tout OK ; sinon `fix(backup-*): …` adapté**

### Task 16 : Validation E2E manuelle (par l'utilisateur)

**Files:**
- (rien — checklist manuelle)

- [ ] **Step 1 : `git push origin dev` puis `./dev-deploy.sh` sur machine 303**

Exécuté par l'utilisateur.

- [ ] **Step 2 : Login + ouvrir page Backups**

Vérifier que les planifs existantes (s'il y en a) sont migrées : `cron_expr` conservé, `remote_connection_ids` peuplé pour les planifs qui avaient un `remote_connection_id`, `keep_local=true` par défaut partout.

- [ ] **Step 3 : Créer une planif via wizard**

- Bouton « + Ajouter »
- Step 1 : « Toutes les heures »
- Step 2 : minute 15
- Step 3 : nom « test-horaire », cocher local, sélectionner 2 remotes (s'il y en a), retention 10
- Enregistrer
- Vérifier en DB : `SELECT cron_expr, keep_local FROM backup_schedules_full WHERE name='test-horaire';` → `15 * * * *`, true
- Vérifier la join : `SELECT remote_connection_id FROM backup_schedule_full_remotes WHERE schedule_id=...;` → 2 rows

- [ ] **Step 4 : Déclencher le job manuellement**

Soit attendre que le cron déclenche, soit via API `POST /api/admin/backup-schedules/full/{id}/run-now` (si endpoint existe).

- [ ] **Step 5 : Vérifier les pushes en DB et UI**

`SELECT status FROM local_backup_pushes WHERE local_backup_id=...;` → 2 rows 'ok'.

Dans l'UI, le local_backup affiche `✓ remote1 · ✓ remote2`.

- [ ] **Step 6 : Tester re-push manuel**

- Forcer une row push à 'failed' via SQL (ou injection d'erreur)
- Vérifier que l'UI affiche `✗ remote` et le menu kebab proposant « Re-pousser vers remote »
- Cliquer → vérifier que le statut redevient `ok`

- [ ] **Step 7 : Tester keep_local=false**

- Créer une nouvelle planif sans cocher « Conserver local », avec 1 remote
- Déclencher
- Vérifier en DB : `SELECT local_file_present FROM local_backups WHERE source_schedule_full_id=...;` → false (si push OK)
- Vérifier le fichier .dump n'existe plus dans `/app/data/backups/` côté container

- [ ] **Step 8 : Si une régression apparaît, partager le détail (logs backend + capture UI)**

---

## Validation finale

- [ ] Migration 114 appliquée, join table créée, push history table créée, data existante préservée
- [ ] Backend : tous les tests verts (8 nouveaux dans `test_local_backup_pushes_service`, 3 nouveaux dans `test_backup_job_runner`, 7 dans `test_migration_114`, 2 nouveaux dans `test_backup_schedules_service`, 4 nouveaux dans `test_admin_backup_schedules` + `test_admin_local_backups`)
- [ ] Frontend : Vitest verts (11 dans `cronWizard.test.ts`, 7 dans `ScheduleWizard.test.tsx`)
- [ ] Ruff + tsc clean
- [ ] `from agflow.main import create_app` OK
- [ ] Aucune trace de `remote_connection_id` mono-FK dans le code (hors join table)
- [ ] Smoke E2E manuel passé sur LXC : création via wizard, run, vérification pushes, re-push, keep_local=false
