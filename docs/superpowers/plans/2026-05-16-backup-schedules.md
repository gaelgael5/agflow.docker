# Backup Schedules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax for tracking. **Référence détaillée** : `docs/superpowers/specs/2026-05-16-backup-schedules-design.md` (spec validée, commit `0ecbcc2`) — tous les schémas SQL, signatures Python et payloads JSON y sont précisés.

**Goal:** Ajouter des planifications de backups (full cron + snapshot interval) avec APScheduler, page Backups refondue, suppression du `remote_backup_pusher`.

**Architecture:** 2 tables `backup_schedules_full` + `backup_schedules_snapshot`. Worker APScheduler (AsyncIOScheduler, tick 30s pour re-sync DB). Job runner per-schedule (`run_full_job`, `run_snapshot_job`) qui crée backup + push remote optionnel + record last_run + prune retention. 12 endpoints admin REST. Page Backups avec 3 sections (full schedules / snapshot schedules / local backups list + filtre source).

**Tech Stack:** Python 3.12 + asyncpg + apscheduler 3.10+ + FastAPI + structlog + pytest / Vite + React 18 + TanStack Query + Zod + i18next

---

## File Structure

### Backend — créés

| Fichier | Responsabilité |
|---|---|
| `backend/migrations/109_backup_schedules.sql` | 2 tables + ALTER local_backups (2 FK + CHECK) + triggers updated_at |
| `backend/src/agflow/schemas/backup_schedules.py` | Pydantic : FullScheduleSummary/Create/Update, SnapshotScheduleSummary/Create/Update |
| `backend/src/agflow/services/backup_schedules_service.py` | CRUD + record_run + prune_old_backups |
| `backend/src/agflow/services/backup_job_runner.py` | run_full_job + run_snapshot_job |
| `backend/src/agflow/services/backup_scheduler.py` | start/stop/reload_schedules/trigger_now (APScheduler wrapper) |
| `backend/src/agflow/api/admin/backup_schedules.py` | 12 endpoints (full+snapshot CRUD + run-now + set-enabled) |
| `backend/tests/services/test_backup_schedules_service.py` | CRUD + validation + record_run + prune |
| `backend/tests/services/test_backup_job_runner.py` | happy path + no remote + remote KO + concurrency |
| `backend/tests/services/test_backup_scheduler.py` | start/stop + reload_schedules diff + trigger_now |
| `backend/tests/api/test_admin_backup_schedules.py` | 12 endpoints : auth, viewer 403, validation, run-now |
| `backend/tests/services/test_local_backups_source_kind.py` | _to_dto dérive source_kind manual/full/snapshot |

### Backend — modifiés

| Fichier | Modification |
|---|---|
| `backend/pyproject.toml` | + `apscheduler>=3.10,<4` |
| `backend/src/agflow/services/local_backups_service.py` | create_backup accepte source_schedule_*_id ; _to_dto dérive source_kind |
| `backend/src/agflow/schemas/local_backups.py` | LocalBackupSummary + source_kind field |
| `backend/src/agflow/main.py` | retire `remote_backup_pusher`, ajoute `backup_scheduler.start/stop` |
| `backend/src/agflow/workers/remote_backup_pusher.py` | **supprimé** |

### Frontend — créés

| Fichier | Responsabilité |
|---|---|
| `frontend/src/lib/backupSchedulesApi.ts` | 12 fonctions REST |
| `frontend/src/hooks/useBackupSchedules.ts` | useFullSchedules + useSnapshotSchedules (refetch 30s) |
| `frontend/src/components/backups/FullSchedulesSection.tsx` | Table + dialog create/edit |
| `frontend/src/components/backups/SnapshotSchedulesSection.tsx` | Table + dialog create/edit |
| `frontend/src/components/backups/BackupNowButton.tsx` | Bouton manuel global |

### Frontend — modifiés

| Fichier | Modification |
|---|---|
| `frontend/src/pages/BackupsPage.tsx` | 3 sections + BackupNowButton |
| `frontend/src/components/LocalBackupsSection.tsx` | Filtre source (manual/full/snapshot/all) |
| `frontend/src/i18n/fr.json` | + ~40 clés `backups.schedules.*` |
| `frontend/src/i18n/en.json` | mêmes clés en EN |

---

## LOT 1 — Foundations

### Task 1 : Migration 109

**Files:**
- Create: `backend/migrations/109_backup_schedules.sql`

- [ ] **Step 1 : Écrire la migration**

Copier le contenu SQL complet depuis `docs/superpowers/specs/2026-05-16-backup-schedules-design.md` section « Migration 109 » (les 2 tables + triggers + ALTER local_backups + 2 INDEX).

- [ ] **Step 2 : Vérifier la syntaxe**

```bash
grep -c "CREATE TABLE\|ALTER TABLE\|CREATE INDEX" backend/migrations/109_backup_schedules.sql
```

Expected : `5` (2 CREATE TABLE + 3 ALTER TABLE + 2 CREATE INDEX = 7 ; le `c` compte les lignes, donc ≥5).

- [ ] **Step 3 : Commit**

```bash
git add backend/migrations/109_backup_schedules.sql
git commit -m "feat(backups-db): migration 109 — backup_schedules_full + snapshot + source_kind"
```

---

### Task 2 : Dépendance APScheduler

**Files:**
- Modify: `backend/pyproject.toml`

- [ ] **Step 1 : Ajouter `apscheduler>=3.10,<4`**

Dans `backend/pyproject.toml`, liste `dependencies = [...]`, ajouter à l'ordre alphabétique :
```toml
    "apscheduler>=3.10,<4",
```

- [ ] **Step 2 : Vérifier `uv sync`**

```bash
cd backend && uv sync 2>&1 | tail -3
```

Expected : `Resolved N packages` sans conflit.

- [ ] **Step 3 : Commit**

```bash
git add backend/pyproject.toml backend/uv.lock
git commit -m "chore(backups): + apscheduler>=3.10,<4"
```

---

### Task 3 : create_backup + source_kind

**Files:**
- Modify: `backend/src/agflow/services/local_backups_service.py`
- Modify: `backend/src/agflow/schemas/local_backups.py`
- Create: `backend/tests/services/test_local_backups_source_kind.py`

- [ ] **Step 1 : Test rouge — source_kind dérivé dans _to_dto**

Créer `backend/tests/services/test_local_backups_source_kind.py` :

```python
"""Tests purs de la dérivation source_kind dans local_backups _to_dto."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from agflow.services.local_backups_service import _to_dto


_NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _row(*, source_full: uuid.UUID | None = None, source_snapshot: uuid.UUID | None = None) -> dict:
    return {
        "id": uuid.uuid4(),
        "filename": "b.sql.gz",
        "file_path": "/tmp/b.sql.gz",
        "size_bytes": 123,
        "status": "completed",
        "created_at": _NOW,
        "created_by_user_id": None,
        "source_schedule_full_id": source_full,
        "source_schedule_snapshot_id": source_snapshot,
        "source_remote_connection_id": None,
    }


def test_source_kind_manual_when_both_null() -> None:
    dto = _to_dto(_row())
    assert dto.source_kind == "manual"


def test_source_kind_full_when_full_id_set() -> None:
    dto = _to_dto(_row(source_full=uuid.uuid4()))
    assert dto.source_kind == "full"


def test_source_kind_snapshot_when_snapshot_id_set() -> None:
    dto = _to_dto(_row(source_snapshot=uuid.uuid4()))
    assert dto.source_kind == "snapshot"
```

- [ ] **Step 2 : Run, expect FAIL** (probable AttributeError ou ValidationError)

```bash
cd backend && uv run pytest tests/services/test_local_backups_source_kind.py -v 2>&1 | tail -5
```

- [ ] **Step 3 : Modifier `LocalBackupSummary` schema**

Dans `backend/src/agflow/schemas/local_backups.py`, ajouter à la classe `LocalBackupSummary` :
```python
    source_kind: Literal["manual", "full", "snapshot"] = "manual"
```
(Import si manquant : `from typing import Literal`)

- [ ] **Step 4 : Modifier `_to_dto`**

Dans `backend/src/agflow/services/local_backups_service.py`, fonction `_to_dto` :
```python
    source_kind = (
        "full" if row.get("source_schedule_full_id") is not None
        else "snapshot" if row.get("source_schedule_snapshot_id") is not None
        else "manual"
    )
    return LocalBackupSummary(
        # ... champs existants ...
        source_kind=source_kind,
    )
```

Vérifier que le SELECT existant inclut bien `source_schedule_full_id`, `source_schedule_snapshot_id` (ajouter si absent — la migration 109 a ajouté ces colonnes).

- [ ] **Step 5 : Modifier `create_backup` signature**

Dans le même fichier, signature de `create_backup` :
```python
async def create_backup(
    *,
    created_by_user_id: UUID | None = None,
    source_schedule_full_id: UUID | None = None,
    source_schedule_snapshot_id: UUID | None = None,
) -> LocalBackupSummary:
```

Note : ajouter `*` avant les params pour rendre tous keyword-only (les callers existants passent déjà `created_by_user_id` en kwarg).

INSERT row : ajouter les 2 colonnes dans VALUES.

- [ ] **Step 6 : Run tests, expect PASS**

```bash
cd backend && uv run pytest tests/services/test_local_backups_source_kind.py -v 2>&1 | tail -5
```

Expected : `3 passed`.

- [ ] **Step 7 : Lint + Commit**

```bash
cd backend && uv run ruff check src/agflow/services/local_backups_service.py src/agflow/schemas/local_backups.py tests/services/test_local_backups_source_kind.py
git add backend/src/agflow/services/local_backups_service.py backend/src/agflow/schemas/local_backups.py backend/tests/services/test_local_backups_source_kind.py
git commit -m "feat(backups-db): create_backup accepte source_schedule_* + dérive source_kind"
```

---

## LOT 2 — Schemas + Service schedules

### Task 4 : Schemas Pydantic backup_schedules

**Files:**
- Create: `backend/src/agflow/schemas/backup_schedules.py`

- [ ] **Step 1 : Créer le fichier**

Référence : spec section « Architecture backend » — API service. Schemas requis :
- `FullScheduleSummary` (id, name, cron_expr, remote_connection_id, retention_count, enabled, last_run_at, last_run_status, last_run_error, created_at, updated_at)
- `FullScheduleCreate` (name min_length=1, cron_expr min_length=1, remote_connection_id optionnel, retention_count default=10 ge=1, enabled default=True)
- `FullScheduleUpdate` (tous champs optionnels)
- `SnapshotScheduleSummary` (idem mais interval_amount + interval_unit au lieu de cron_expr)
- `SnapshotScheduleCreate` (name, interval_amount ge=1, interval_unit Literal['minutes','hours'], remote_connection_id?, retention_count default=24, enabled default=True)
- `SnapshotScheduleUpdate`

Utiliser `from __future__ import annotations`, `Pydantic v2 ConfigDict(from_attributes=True)`, `Literal` pour les enums.

- [ ] **Step 2 : Lint + Commit**

```bash
cd backend && uv run ruff check src/agflow/schemas/backup_schedules.py
git add backend/src/agflow/schemas/backup_schedules.py
git commit -m "feat(backups-schedules): schemas Pydantic full + snapshot"
```

---

### Task 5 : Service backup_schedules_service (CRUD full)

**Files:**
- Create: `backend/src/agflow/services/backup_schedules_service.py`
- Create: `backend/tests/services/test_backup_schedules_service.py`

- [ ] **Step 1 : Tests rouges CRUD full**

`backend/tests/services/test_backup_schedules_service.py` — tests d'intégration (fixture `fresh_db` qui appelle `reset_schema_and_migrate`) :

```python
"""Tests intégration du service backup_schedules (DB réelle)."""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest

from agflow.services import backup_schedules_service as svc
from agflow.schemas.backup_schedules import (
    FullScheduleCreate, FullScheduleUpdate,
    SnapshotScheduleCreate, SnapshotScheduleUpdate,
)
from tests._db_reset import reset_schema_and_migrate


@pytest.fixture
async def fresh_db() -> AsyncIterator[None]:
    await reset_schema_and_migrate()
    yield


async def _create_admin() -> uuid.UUID:
    from agflow.db.pool import execute
    uid = uuid.uuid4()
    await execute(
        "INSERT INTO users (id, email, name, role, status) VALUES ($1, $2, 'a', 'admin', 'active')",
        uid, f"a-{uid}@x.com",
    )
    return uid


@pytest.mark.asyncio
async def test_create_full_schedule(fresh_db) -> None:
    actor = await _create_admin()
    out = await svc.create_full_schedule(
        FullScheduleCreate(name="daily", cron_expr="0 3 * * *", retention_count=5),
        actor_user_id=actor,
    )
    assert out.name == "daily"
    assert out.cron_expr == "0 3 * * *"
    assert out.retention_count == 5
    assert out.enabled is True
    assert out.last_run_at is None


@pytest.mark.asyncio
async def test_create_full_rejects_invalid_cron(fresh_db) -> None:
    actor = await _create_admin()
    with pytest.raises(svc.InvalidCronExpressionError):
        await svc.create_full_schedule(
            FullScheduleCreate(name="bad", cron_expr="not a cron"),
            actor_user_id=actor,
        )


@pytest.mark.asyncio
async def test_list_full_schedules_returns_created(fresh_db) -> None:
    actor = await _create_admin()
    await svc.create_full_schedule(FullScheduleCreate(name="a", cron_expr="0 * * * *"), actor_user_id=actor)
    await svc.create_full_schedule(FullScheduleCreate(name="b", cron_expr="0 0 * * *"), actor_user_id=actor)
    items = await svc.list_full_schedules()
    assert len(items) == 2
    assert {i.name for i in items} == {"a", "b"}


@pytest.mark.asyncio
async def test_update_full_changes_fields(fresh_db) -> None:
    actor = await _create_admin()
    created = await svc.create_full_schedule(FullScheduleCreate(name="x", cron_expr="0 * * * *"), actor_user_id=actor)
    updated = await svc.update_full_schedule(
        created.id, FullScheduleUpdate(name="y", retention_count=42),
    )
    assert updated.name == "y"
    assert updated.retention_count == 42


@pytest.mark.asyncio
async def test_delete_full_removes_row(fresh_db) -> None:
    actor = await _create_admin()
    created = await svc.create_full_schedule(FullScheduleCreate(name="x", cron_expr="0 * * * *"), actor_user_id=actor)
    await svc.delete_full_schedule(created.id)
    with pytest.raises(svc.ScheduleNotFoundError):
        await svc.get_full_schedule(created.id)


@pytest.mark.asyncio
async def test_set_full_enabled_toggles(fresh_db) -> None:
    actor = await _create_admin()
    created = await svc.create_full_schedule(FullScheduleCreate(name="x", cron_expr="0 * * * *"), actor_user_id=actor)
    assert created.enabled is True
    disabled = await svc.set_full_enabled(created.id, False)
    assert disabled.enabled is False
```

- [ ] **Step 2 : Run, expect FAIL** (ModuleNotFoundError)

- [ ] **Step 3 : Implémenter service CRUD full + exceptions**

Créer `backend/src/agflow/services/backup_schedules_service.py` :
- Exceptions : `ScheduleNotFoundError`, `InvalidCronExpressionError`, `InvalidIntervalError`
- Helpers : `_validate_cron(expr) -> None` (via `croniter`)
- Helpers : `_to_full_summary(row)`, `_to_snapshot_summary(row)`
- Fonctions CRUD full : list_full_schedules, get_full_schedule, create_full_schedule, update_full_schedule, delete_full_schedule, set_full_enabled

`croniter` est installé comme dépendance transitive d'APScheduler.

- [ ] **Step 4 : Run, expect PASS** (6 passed)

- [ ] **Step 5 : Commit**

```bash
git add backend/src/agflow/services/backup_schedules_service.py backend/tests/services/test_backup_schedules_service.py
git commit -m "feat(backups-schedules): service CRUD full + validation cron"
```

---

### Task 6 : Service snapshot + record_run + prune

**Files:**
- Modify: `backend/src/agflow/services/backup_schedules_service.py`
- Modify: `backend/tests/services/test_backup_schedules_service.py`

- [ ] **Step 1 : Ajouter tests rouges**

Ajouter aux tests :
- `test_create_snapshot_schedule` (interval_amount=15, interval_unit='minutes')
- `test_create_snapshot_rejects_invalid_interval` (amount=0 → ValueError Pydantic → 422 backend, ou InvalidIntervalError si on valide manuellement)
- `test_update_snapshot`, `test_delete_snapshot`, `test_set_snapshot_enabled`
- `test_record_run_updates_last_run_fields` (status='ok' puis 'failed' + error)
- `test_prune_old_backups_keeps_n_latest` (créer 5 local_backups liés à 1 schedule, retention_count=2, vérifier qu'il reste 2 + fichiers supprimés via mocker `Path.unlink` ou créer/supprimer de vrais fichiers temp)

- [ ] **Step 2 : Run, expect FAIL**

- [ ] **Step 3 : Implémenter snapshot CRUD + record_run + prune_old_backups**

Ajouter dans le service :
- list/get/create/update/delete/set_enabled snapshot
- `record_run(*, schedule_id, kind: Literal['full','snapshot'], status, error=None)` → UPDATE selon kind
- `prune_old_backups(*, schedule_id, kind, retention_count) -> int` :
  - SELECT id, file_path FROM local_backups WHERE source_schedule_{kind}_id = $1 ORDER BY created_at DESC OFFSET retention_count
  - Pour chaque row : Path(file_path).unlink(missing_ok=True) + DELETE FROM local_backups WHERE id = $1
  - Retourne le nombre supprimé

- [ ] **Step 4 : Run, expect PASS**

- [ ] **Step 5 : Commit**

```bash
git add backend/src/agflow/services/backup_schedules_service.py backend/tests/services/test_backup_schedules_service.py
git commit -m "feat(backups-schedules): snapshot CRUD + record_run + prune_old_backups"
```

---

## LOT 3 — Job runner + Scheduler

### Task 7 : backup_job_runner (full)

**Files:**
- Create: `backend/src/agflow/services/backup_job_runner.py`
- Create: `backend/tests/services/test_backup_job_runner.py`

- [ ] **Step 1 : Tests rouges run_full_job**

Tests d'intégration DB + mocks providers :
- `test_run_full_job_happy_path_no_remote` (crée backup, last_run='ok', no push)
- `test_run_full_job_with_remote_push_ok` (mock provider.upload_stream, vérifie appel)
- `test_run_full_job_remote_push_failed` (provider lève, status='failed', backup local préservé)
- `test_run_full_job_skipped_if_disabled` (schedule enabled=false → no-op)
- `test_run_full_job_prunes_after_run` (création de plusieurs backups simulés, retention=2)

- [ ] **Step 2 : Run, expect FAIL**

- [ ] **Step 3 : Implémenter run_full_job**

Référence : spec section « Job runner ». Code structuré try/except global. `local_backups_service.create_backup(source_schedule_full_id=schedule_id)` puis push optionnel via `rbc_service.fetch_credentials` + `get_provider`.

- [ ] **Step 4 : Run, expect PASS** + Commit

```bash
git add backend/src/agflow/services/backup_job_runner.py backend/tests/services/test_backup_job_runner.py
git commit -m "feat(backups-scheduler): run_full_job (create + push + record + prune)"
```

---

### Task 8 : backup_job_runner (snapshot)

**Files:**
- Modify: `backend/src/agflow/services/backup_job_runner.py`
- Modify: `backend/tests/services/test_backup_job_runner.py`

- [ ] **Step 1 : Tests rouges run_snapshot_job** (mêmes cas que full)

- [ ] **Step 2 : Run, expect FAIL**

- [ ] **Step 3 : Implémenter run_snapshot_job**

Identique à run_full_job mais utilise `source_schedule_snapshot_id` + `kind='snapshot'`.

- [ ] **Step 4 : Run, expect PASS** + Commit

```bash
git add backend/src/agflow/services/backup_job_runner.py backend/tests/services/test_backup_job_runner.py
git commit -m "feat(backups-scheduler): run_snapshot_job"
```

---

### Task 9 : backup_scheduler APScheduler + suppression remote_backup_pusher

**Files:**
- Create: `backend/src/agflow/services/backup_scheduler.py`
- Create: `backend/tests/services/test_backup_scheduler.py`
- Modify: `backend/src/agflow/main.py`
- Delete: `backend/src/agflow/workers/remote_backup_pusher.py`

- [ ] **Step 1 : Tests rouges scheduler**

Tests unit (mock AsyncIOScheduler) :
- `test_start_creates_scheduler_and_calls_reload`
- `test_reload_schedules_adds_new_jobs_from_db`
- `test_reload_schedules_removes_orphan_jobs`
- `test_trigger_now_calls_add_job_with_now`
- `test_stop_shutdowns_scheduler`

- [ ] **Step 2 : Run, expect FAIL**

- [ ] **Step 3 : Implémenter backup_scheduler**

Pattern :
```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

_scheduler: AsyncIOScheduler | None = None

async def start() -> None: ...
async def stop() -> None: ...
async def reload_schedules() -> None: ...
async def trigger_now(*, schedule_id, kind): ...
```

`reload_schedules` : lit les 2 tables, diff avec `_scheduler.get_jobs()` par id, ADD/MODIFY/REMOVE.

Démarrer un second `add_job(reload_schedules, IntervalTrigger(seconds=30))` lors de `start()` pour le re-sync périodique.

- [ ] **Step 4 : Run, expect PASS**

- [ ] **Step 5 : Brancher dans `main.py` + supprimer remote_backup_pusher**

Dans `main.py` :
- Retirer l'import `_run_remote_backup_pusher_loop`
- Retirer `_asyncio.create_task(_run_remote_backup_pusher_loop(_stops[4]))` et adapter l'array `_stops` (passer de 6 à 5 éléments si applicable, OU laisser un slot vide — vérifier la cohérence avec `_stops` utilisé ailleurs)
- Ajouter import `from agflow.services.backup_scheduler import start as _backup_scheduler_start, stop as _backup_scheduler_stop`
- Dans lifespan, avant le `yield` : `await _backup_scheduler_start()`
- Dans cleanup après yield : `await _backup_scheduler_stop()`

```bash
git rm backend/src/agflow/workers/remote_backup_pusher.py
```

- [ ] **Step 6 : Smoke import app**

```bash
cd backend && uv run python -c "from agflow.main import create_app; create_app(); print('OK')"
```

- [ ] **Step 7 : Commit**

```bash
git add backend/src/agflow/services/backup_scheduler.py backend/tests/services/test_backup_scheduler.py backend/src/agflow/main.py
git commit -m "feat(backups-scheduler): APScheduler wrapper + branchement lifespan + suppression remote_backup_pusher"
```

---

## LOT 4 — API admin

### Task 10 : 12 endpoints backup_schedules

**Files:**
- Create: `backend/src/agflow/api/admin/backup_schedules.py`
- Create: `backend/tests/api/test_admin_backup_schedules.py`
- Modify: `backend/src/agflow/main.py`

- [ ] **Step 1 : Tests rouges 12 endpoints**

Pour chaque endpoint (12) : 1 test happy path + tests 401/403/404/422 selon applicable.

Préfixe router : `/api/admin/backup-schedules`. Tests utilisent mocks du service (`patch("agflow.api.admin.backup_schedules.svc.create_full_schedule", AsyncMock(return_value=...))`).

- [ ] **Step 2 : Run, expect FAIL** (404 sur tous les paths)

- [ ] **Step 3 : Implémenter le router**

Référence : spec section « API admin » — tableau des 12 endpoints. Pattern récup user_id :
```python
admin_email: str = Depends(require_admin)
admin_user = await users_service.get_by_email(admin_email)
```

Run-now appelle `backup_scheduler.trigger_now(schedule_id=..., kind='full'|'snapshot')`.

- [ ] **Step 4 : Brancher le router dans `main.py`**

```python
from agflow.api.admin.backup_schedules import router as admin_backup_schedules_router
# ...
app.include_router(admin_backup_schedules_router)
```

- [ ] **Step 5 : Run, expect PASS** (12+ passed)

- [ ] **Step 6 : Commit**

```bash
git add backend/src/agflow/api/admin/backup_schedules.py backend/tests/api/test_admin_backup_schedules.py backend/src/agflow/main.py
git commit -m "feat(backups-api): 12 endpoints backup_schedules (full + snapshot CRUD + run-now + set-enabled)"
```

---

## LOT 5 — Frontend

### Task 11 : api client + hook

**Files:**
- Create: `frontend/src/lib/backupSchedulesApi.ts`
- Create: `frontend/src/hooks/useBackupSchedules.ts`

- [ ] **Step 1 : Créer api client**

Référence : spec section « API client » — interfaces FullScheduleSummary, SnapshotScheduleSummary, CreateFullPayload, CreateSnapshotPayload + 12 fonctions REST.

- [ ] **Step 2 : Créer hook React Query**

`useFullSchedules()` et `useSnapshotSchedules()` avec `useQuery` + mutations create/update/remove/runNow/setEnabled. `refetchInterval: 30_000`.

- [ ] **Step 3 : tsc check + commit**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -10
git add frontend/src/lib/backupSchedulesApi.ts frontend/src/hooks/useBackupSchedules.ts
git commit -m "feat(backups-ui): backupSchedulesApi + useBackupSchedules hook"
```

---

### Task 12 : FullSchedulesSection + i18n (presets cron)

**Files:**
- Create: `frontend/src/components/backups/FullSchedulesSection.tsx`
- Modify: `frontend/src/i18n/fr.json`
- Modify: `frontend/src/i18n/en.json`

- [ ] **Step 1 : Ajouter clés i18n FR + EN**

Sous `backups.schedules.*` (sous-clé existante `backups`) : voir spec « i18n » pour la liste complète des ~40 clés. Pour T12, ajouter au moins les clés `full*`, `col*`, `cronPresets.*`, `runNow*`, `formCron*`, `formRetention*`, `formRemote*`, `lastRun*`, `delete*`, `toggleEnabled`, `enabled`, `disabled`, `addFull`.

JSON valide : `node -e "JSON.parse(require('fs').readFileSync('frontend/src/i18n/fr.json'))"`

- [ ] **Step 2 : Créer FullSchedulesSection**

Référence : spec section « Composants » + « Dialog create/edit » (form full).

Structure : Card avec header (title + bouton Ajouter), tableau (Nom, Cron, Remote, Rétention, LastRun, Actions), Dialog create/edit avec presets cron buttons.

Toggle enabled = `<input type="checkbox">` (pas de Switch shadcn chez nous, cf. HarpocrateVaultsTab pattern).

Run now = bouton avec icône `Play` de lucide-react. Mutate via hook + toast succès/erreur.

Edit/Delete = ConfirmDialog pour delete.

- [ ] **Step 3 : tsc check**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -10
```

- [ ] **Step 4 : Commit**

```bash
git add frontend/src/components/backups/FullSchedulesSection.tsx frontend/src/i18n/fr.json frontend/src/i18n/en.json
git commit -m "feat(backups-ui): FullSchedulesSection + i18n cron presets"
```

---

### Task 13 : SnapshotSchedulesSection + BackupNowButton

**Files:**
- Create: `frontend/src/components/backups/SnapshotSchedulesSection.tsx`
- Create: `frontend/src/components/backups/BackupNowButton.tsx`
- Modify: `frontend/src/i18n/fr.json`
- Modify: `frontend/src/i18n/en.json`

- [ ] **Step 1 : Ajouter clés i18n snapshots + backupNow**

Clés manquantes (`snapshotTitle`, `addSnapshot`, `formIntervalLabel`, `formIntervalAmount`, `formIntervalUnit`, `colInterval`, `backupNowButton`, `backupNowSuccess`, `backupNowError`).

- [ ] **Step 2 : Créer SnapshotSchedulesSection**

Structure quasi-identique à FullSchedulesSection mais form a `interval_amount` (input number) + `interval_unit` (select Minutes/Heures) à la place du cron.

Affichage interval dans le tableau : `{amount} {unit_short}` (15 min, 1 h, 6 h).

- [ ] **Step 3 : Créer BackupNowButton**

Petit composant qui appelle `POST /api/admin/local-backups` (endpoint existant) avec toast success/error. Loading state pendant la création.

- [ ] **Step 4 : tsc + commit**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -10
git add frontend/src/components/backups/SnapshotSchedulesSection.tsx frontend/src/components/backups/BackupNowButton.tsx frontend/src/i18n/fr.json frontend/src/i18n/en.json
git commit -m "feat(backups-ui): SnapshotSchedulesSection + BackupNowButton"
```

---

### Task 14 : Intégration BackupsPage + filtre source LocalBackupsSection

**Files:**
- Modify: `frontend/src/pages/BackupsPage.tsx`
- Modify: `frontend/src/components/LocalBackupsSection.tsx`
- Modify: `frontend/src/i18n/fr.json`
- Modify: `frontend/src/i18n/en.json`

- [ ] **Step 1 : Ajouter clés i18n filtre**

`filterSource`, `filterAll`, `filterManual`, `filterFull`, `filterSnapshot`.

- [ ] **Step 2 : Modifier BackupsPage**

```tsx
import { BackupNowButton } from "@/components/backups/BackupNowButton";
import { FullSchedulesSection } from "@/components/backups/FullSchedulesSection";
import { SnapshotSchedulesSection } from "@/components/backups/SnapshotSchedulesSection";

export function BackupsPage() {
  return (
    <div className="...">
      <h1>{t("backups.page_title")}</h1>
      <BackupNowButton />
      <FullSchedulesSection />
      <SnapshotSchedulesSection />
      <LocalBackupsSection />
      <RemoteBackupsBrowser />
    </div>
  );
}
```

- [ ] **Step 3 : Filtre source dans LocalBackupsSection**

Ajouter un Select au-dessus du tableau : "Toutes / Manuelles / Pleines / Snapshots". State local `sourceFilter`, filtre côté client sur `b.source_kind`. Le backend retourne déjà `source_kind` via le DTO étendu en T3.

- [ ] **Step 4 : tsc + commit**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -10
git add frontend/src/pages/BackupsPage.tsx frontend/src/components/LocalBackupsSection.tsx frontend/src/i18n/fr.json frontend/src/i18n/en.json
git commit -m "feat(backups-ui): BackupsPage 3 sections + filtre source sur liste"
```

---

## LOT 6 — Validation E2E

### Task 15 : run-test.sh final

**Files:** aucun changement code

- [ ] **Step 1 : Push**

```bash
git push origin dev
```

- [ ] **Step 2 : Run-test CLEANUP=1**

```bash
CLEANUP=1 ./scripts/run-test.sh
```

Expected : `Tests OK : 8/8` + `~35 nouveaux tests gdrive verts` dans pytest.

- [ ] **Step 3 : Smoke métier manuel (post-déploiement)**

Sur LXC live :
1. Créer un coffre Harpocrate default (sinon les push remote vaultés plantent)
2. Créer une connexion S3/sftp (cf. smoke S3 précédent)
3. Créer un schedule snapshot interval=1 minute pointant vers cette connexion
4. Attendre 60s
5. Vérifier que :
   - Un backup apparaît dans la liste avec `source_kind: snapshot`
   - Le fichier est uploadé sur le remote configuré
   - `last_run_at` est mis à jour avec status='ok'
   - Au bout de N+1 ticks (avec retention=N), les vieux backups sont supprimés (DB + fichier)

---

## Récap commits

15 commits attendus :
- T1 `feat(backups-db): migration 109 — backup_schedules_full + snapshot + source_kind`
- T2 `chore(backups): + apscheduler>=3.10,<4`
- T3 `feat(backups-db): create_backup accepte source_schedule_* + dérive source_kind`
- T4 `feat(backups-schedules): schemas Pydantic full + snapshot`
- T5 `feat(backups-schedules): service CRUD full + validation cron`
- T6 `feat(backups-schedules): snapshot CRUD + record_run + prune_old_backups`
- T7 `feat(backups-scheduler): run_full_job (create + push + record + prune)`
- T8 `feat(backups-scheduler): run_snapshot_job`
- T9 `feat(backups-scheduler): APScheduler wrapper + branchement lifespan + suppression remote_backup_pusher`
- T10 `feat(backups-api): 12 endpoints backup_schedules`
- T11 `feat(backups-ui): backupSchedulesApi + useBackupSchedules hook`
- T12 `feat(backups-ui): FullSchedulesSection + i18n cron presets`
- T13 `feat(backups-ui): SnapshotSchedulesSection + BackupNowButton`
- T14 `feat(backups-ui): BackupsPage 3 sections + filtre source sur liste`
- T15 (pas de commit, validation E2E)

---

## Notes finales

- À chaque task implémentation : se référer au **spec** `docs/superpowers/specs/2026-05-16-backup-schedules-design.md` pour les détails (SQL complet, signatures Python, payloads JSON exacts).
- CLAUDE.md : pas de quick-and-dirty, branche `dev` uniquement, fichiers ≤ 300 lignes (split si T5 ou T12 dépassent).
- Si un test fail au LOT 2-4 (backend) à cause de DB locale injoignable depuis Windows (cf. expérience gdrive), c'est acceptable en DONE_WITH_CONCERNS — la validation E2E à T15 sur LXC fresh validera tout.
- Au LOT 3 (Task 9), la suppression du `remote_backup_pusher` est un changement comportemental : aucune migration de données nécessaire (le pusher ne maintenait pas d'état persistant), mais documenter dans le commit que la fonctionnalité « push automatique des snapshots » est désormais explicite via schedules.
