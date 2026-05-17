# Git Sync — Intégration métier (plan d'implémentation)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Brancher le SDK Git Sync (`backend/sdk/git_sync/`) dans le métier d'agflow.docker : table singleton de config, services backend, scheduler APScheduler, 9 endpoints admin, onglet UI dans `/settings`.

**Architecture:** Couche service fine au-dessus du SDK générique. Singleton DB (`git_sync_config` CHECK id=1) pour la persistance. Worker APScheduler dédié (séparé de backup_scheduler). Onglet React dans SettingsPage avec 3 sous-composants (Config/Actions/History) qui consomment 9 endpoints REST sous `/api/admin/git-sync`.

**Tech Stack:** Python 3.12 + FastAPI + asyncpg + APScheduler 3.x + Harpocrate SDK + httpx · React 18 + TanStack Query + Zod + shadcn/ui + i18next.

**Spec de référence :** `docs/superpowers/specs/2026-05-17-git-sync-integration-design.md` (commit f1dd3c0).

**Branche cible :** `dev`. Pas de feature branch.

**Mode pipeline allégé** (validé sur backup_schedules) : implementer subagent seul, pas de spec-reviewer ni code-reviewer intermédiaires entre tâches. Exécution continue (pas d'arrêt entre tâches sauf BLOCKED).

**Note sur les tests d'intégration DB** : depuis Windows, le LXC 201 Postgres peut être injoignable → DONE_WITH_CONCERNS acceptable, validation E2E à T11 via `./scripts/run-test.sh`.

---

## Structure des fichiers (vue d'ensemble)

### Backend

| Fichier | Responsabilité | Lignes cible |
|---|---|---|
| `backend/migrations/110_git_sync_config.sql` | Migration table singleton | ~50 |
| `backend/src/agflow/schemas/git_sync.py` | DTOs Pydantic (config + résultats + commits) | ~140 |
| `backend/src/agflow/services/git_sync_service.py` | CRUD config singleton + list_available_tables + record_*_run | ~180 |
| `backend/src/agflow/services/git_sync_runner.py` | Wrappers SDK (run_export / run_preview / run_import) + résolution Harpocrate | ~140 |
| `backend/src/agflow/services/git_sync_github_client.py` | parse_repo_url + list_commits via httpx | ~120 |
| `backend/src/agflow/services/git_sync_scheduler.py` | AsyncIOScheduler dédié + tick reload + trigger_now | ~120 |
| `backend/src/agflow/api/admin/git_sync.py` | 9 endpoints REST | ~150 |
| `backend/src/agflow/main.py` | Branchement lifespan + include_router | +6 lignes |

### Frontend

| Fichier | Responsabilité | Lignes cible |
|---|---|---|
| `frontend/src/lib/gitSyncApi.ts` | 9 fonctions API + types | ~140 |
| `frontend/src/hooks/useGitSync.ts` | Hooks TanStack Query (3 queries + 6 mutations) | ~120 |
| `frontend/src/components/settings/GitSyncTab.tsx` | Wrapper + état vide / configuré | ~80 |
| `frontend/src/components/settings/GitSyncConfigSection.tsx` | Card récap config + boutons Modifier/Supprimer | ~150 |
| `frontend/src/components/settings/GitSyncConfigDialog.tsx` | Form complet (Zod) + bouton test Harpocrate | ~250 |
| `frontend/src/components/settings/GitSyncActionsSection.tsx` | 3 boutons + cards last_export / last_import | ~180 |
| `frontend/src/components/settings/GitSyncPreviewDialog.tsx` | Preview import + bouton lancer import | ~140 |
| `frontend/src/components/settings/GitSyncHistorySection.tsx` | Table commits GitHub | ~120 |
| `frontend/src/pages/SettingsPage.tsx` | Ajout onglet `Git Sync` | +6 lignes |
| `frontend/src/i18n/fr.json` | ~50 clés `settings.gitSync.*` | +60 lignes |
| `frontend/src/i18n/en.json` | ~50 clés `settings.gitSync.*` | +60 lignes |

### Tests

| Fichier | Tests |
|---|---|
| `backend/tests/services/test_git_sync_service.py` | ~8 tests (singleton, CRUD, list_tables, record_*) |
| `backend/tests/services/test_git_sync_github_client.py` | ~6 tests (parse_repo_url + list_commits mock httpx) |
| `backend/tests/services/test_git_sync_runner.py` | ~6 tests (export/preview/import wrappers mock SDK) |
| `backend/tests/services/test_git_sync_scheduler.py` | ~5 tests (start/stop/reload/trigger_now) |
| `backend/tests/api/test_admin_git_sync.py` | ~10 tests (9 endpoints + cas d'erreur) |
| `frontend/src/lib/__tests__/gitSyncApi.test.ts` | ~4 tests (Zod schemas + parsing) |
| `frontend/src/hooks/__tests__/useGitSync.test.ts` | ~4 tests (mutations invalidations) |

---

## Tâche 1 — Migration 110 + Schémas Pydantic

**Files:**
- Create: `backend/migrations/110_git_sync_config.sql`
- Create: `backend/src/agflow/schemas/git_sync.py`
- Test: `backend/tests/db/test_migration_110.py`

### Step 1 — Écrire le test de migration (failing)

- [ ] Créer `backend/tests/db/test_migration_110.py` :

```python
"""Test de la migration 110 — git_sync_config table singleton."""
from __future__ import annotations

import pytest
from asyncpg import UniqueViolationError

pytestmark = pytest.mark.asyncio


async def test_singleton_constraint_rejects_second_insert(fresh_db):
    """CHECK (id = 1) + PRIMARY KEY garantit le singleton."""
    await fresh_db.execute(
        """
        INSERT INTO git_sync_config (id, repo_url, auth_mode, auth_secret_ref)
        VALUES (1, 'https://github.com/owner/repo', 'pat_https', 'vault/git/pat')
        """
    )
    with pytest.raises(UniqueViolationError):
        await fresh_db.execute(
            """
            INSERT INTO git_sync_config (id, repo_url, auth_mode, auth_secret_ref)
            VALUES (1, 'https://github.com/other/repo', 'pat_https', 'vault/git/pat2')
            """
        )


async def test_default_values_applied(fresh_db):
    """Les colonnes avec DEFAULT sont remplies sans les passer dans l'INSERT."""
    await fresh_db.execute(
        """
        INSERT INTO git_sync_config (repo_url, auth_mode, auth_secret_ref)
        VALUES ('https://github.com/owner/repo', 'pat_https', 'vault/git/pat')
        """
    )
    row = await fresh_db.fetchrow("SELECT * FROM git_sync_config WHERE id = 1")
    assert row["id"] == 1
    assert row["branch"] == "main"
    assert row["commit_author_name"] == "agflow bot"
    assert row["commit_author_email"] == "bot@agflow.local"
    assert row["excluded_columns"] == "{}"
    assert row["selected_tables"] == "[]"
    assert row["cron_enabled"] is False
    assert row["created_at"] is not None
    assert row["updated_at"] is not None


async def test_auth_mode_check_constraint(fresh_db):
    """auth_mode CHECK rejette les valeurs hors enum."""
    from asyncpg.exceptions import CheckViolationError

    with pytest.raises(CheckViolationError):
        await fresh_db.execute(
            """
            INSERT INTO git_sync_config (repo_url, auth_mode, auth_secret_ref)
            VALUES ('url', 'invalid_mode', 'vault/path')
            """
        )


async def test_updated_at_trigger(fresh_db):
    """Le trigger set_updated_at() met à jour updated_at à chaque UPDATE."""
    await fresh_db.execute(
        """
        INSERT INTO git_sync_config (repo_url, auth_mode, auth_secret_ref)
        VALUES ('url', 'pat_https', 'vault/path')
        """
    )
    before = await fresh_db.fetchval("SELECT updated_at FROM git_sync_config WHERE id = 1")
    await fresh_db.execute("UPDATE git_sync_config SET branch = 'develop' WHERE id = 1")
    after = await fresh_db.fetchval("SELECT updated_at FROM git_sync_config WHERE id = 1")
    assert after > before
```

### Step 2 — Vérifier l'échec

- [ ] Lancer : `cd backend && uv run pytest tests/db/test_migration_110.py -v`
- [ ] Attendu : `UndefinedTableError: relation "git_sync_config" does not exist`.

### Step 3 — Écrire la migration

- [ ] Créer `backend/migrations/110_git_sync_config.sql` :

```sql
-- 110_git_sync_config.sql — Configuration singleton de la synchronisation Git

CREATE TABLE git_sync_config (
    id                        int PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    repo_url                  text NOT NULL,
    auth_mode                 text NOT NULL CHECK (auth_mode IN ('ssh_key', 'pat_https', 'basic_https')),
    auth_secret_ref           text NOT NULL,
    branch                    text NOT NULL DEFAULT 'main',
    commit_author_name        text NOT NULL DEFAULT 'agflow bot',
    commit_author_email       text NOT NULL DEFAULT 'bot@agflow.local',
    excluded_columns          jsonb NOT NULL DEFAULT '{}'::jsonb,
    selected_tables           jsonb NOT NULL DEFAULT '[]'::jsonb,
    cron_expr                 text,
    cron_enabled              boolean NOT NULL DEFAULT false,
    last_export_at            timestamptz,
    last_export_status        text CHECK (last_export_status IN ('ok', 'failed')),
    last_export_sha           text,
    last_export_error         text,
    last_export_tables_count  int,
    last_import_at            timestamptz,
    last_import_status        text CHECK (last_import_status IN ('ok', 'failed')),
    last_import_error         text,
    last_import_rows_inserted int,
    last_import_rows_updated  int,
    last_import_rows_deleted  int,
    created_at                timestamptz NOT NULL DEFAULT now(),
    updated_at                timestamptz NOT NULL DEFAULT now()
);

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_git_sync_config_updated_at') THEN
        CREATE TRIGGER trg_git_sync_config_updated_at
            BEFORE UPDATE ON git_sync_config
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
END $$;
```

### Step 4 — Lancer le test (passing)

- [ ] Lancer : `cd backend && uv run pytest tests/db/test_migration_110.py -v`
- [ ] Attendu : 4 tests PASSED.

### Step 5 — Écrire les schémas Pydantic

- [ ] Créer `backend/src/agflow/schemas/git_sync.py` :

```python
"""DTOs Pydantic pour l'intégration métier Git Sync."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from apscheduler.triggers.cron import CronTrigger
from pydantic import BaseModel, Field, field_validator

AuthMode = Literal["ssh_key", "pat_https", "basic_https"]
RunStatus = Literal["ok", "failed"]


class GitSyncConfigDTO(BaseModel):
    repo_url: str
    auth_mode: AuthMode
    auth_secret_ref: str
    branch: str
    commit_author_name: str
    commit_author_email: str
    excluded_columns: dict[str, list[str]]
    selected_tables: list[str]
    cron_expr: str | None
    cron_enabled: bool
    last_export_at: datetime | None
    last_export_status: RunStatus | None
    last_export_sha: str | None
    last_export_error: str | None
    last_export_tables_count: int | None
    last_import_at: datetime | None
    last_import_status: RunStatus | None
    last_import_error: str | None
    last_import_rows_inserted: int | None
    last_import_rows_updated: int | None
    last_import_rows_deleted: int | None
    created_at: datetime
    updated_at: datetime


class GitSyncConfigUpsert(BaseModel):
    repo_url: str = Field(min_length=1)
    auth_mode: AuthMode
    auth_secret_ref: str = Field(min_length=1)
    branch: str = Field(min_length=1, default="main")
    commit_author_name: str = Field(min_length=1, default="agflow bot")
    commit_author_email: str = Field(min_length=1, default="bot@agflow.local")
    excluded_columns: dict[str, list[str]] = Field(default_factory=dict)
    selected_tables: list[str] = Field(min_length=1)
    cron_expr: str | None = None
    cron_enabled: bool = False

    @field_validator("cron_expr")
    @classmethod
    def _validate_cron(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        try:
            CronTrigger.from_crontab(v)
        except ValueError as exc:
            raise ValueError(f"invalid cron expression {v!r}: {exc}") from exc
        return v


class GitSyncTestSecretRefRequest(BaseModel):
    auth_secret_ref: str = Field(min_length=1)


class GitSyncTestSecretRefResult(BaseModel):
    ok: bool
    error: str | None = None


class GitSyncExportResult(BaseModel):
    sha: str
    tables_count: int


class GitSyncTablePreview(BaseModel):
    table: str
    to_insert: int
    to_update: int
    to_delete: int


class GitSyncImportPreviewResult(BaseModel):
    tables: list[GitSyncTablePreview]


class GitSyncImportResult(BaseModel):
    rows_inserted: int
    rows_updated: int
    rows_deleted: int


class GitSyncCommitDTO(BaseModel):
    sha: str
    short_sha: str
    message: str
    author_name: str
    author_email: str
    authored_at: datetime
    html_url: str
```

### Step 6 — Lint

- [ ] Lancer : `cd backend && uv run ruff check src/agflow/schemas/git_sync.py`
- [ ] Attendu : All checks passed.

### Step 7 — Commit

- [ ] Lancer :

```bash
git add backend/migrations/110_git_sync_config.sql backend/src/agflow/schemas/git_sync.py backend/tests/db/test_migration_110.py
git commit -m "feat(git-sync-db): migration 110 git_sync_config (singleton) + schémas Pydantic"
```

---

## Tâche 2 — Service git_sync_service (CRUD config + utils DB)

**Files:**
- Create: `backend/src/agflow/services/git_sync_service.py`
- Test: `backend/tests/services/test_git_sync_service.py`

### Step 1 — Écrire les tests (failing)

- [ ] Créer `backend/tests/services/test_git_sync_service.py` :

```python
"""Tests du service git_sync_service (CRUD config singleton + utils DB)."""
from __future__ import annotations

import pytest

from agflow.services import git_sync_service as svc

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
async def _clean_table(fresh_db):
    await fresh_db.execute("DELETE FROM git_sync_config")
    yield


async def test_get_config_returns_none_when_empty():
    config = await svc.get_config()
    assert config is None


async def test_upsert_config_creates_singleton():
    config = await svc.upsert_config(
        repo_url="https://github.com/owner/repo",
        auth_mode="pat_https",
        auth_secret_ref="${vault://default:git/pat}",
        branch="main",
        commit_author_name="agflow bot",
        commit_author_email="bot@agflow.local",
        excluded_columns={"users": ["password_hash"]},
        selected_tables=["infra_categories"],
        cron_expr=None,
        cron_enabled=False,
    )
    assert config.repo_url == "https://github.com/owner/repo"
    assert config.selected_tables == ["infra_categories"]
    assert config.excluded_columns == {"users": ["password_hash"]}


async def test_upsert_config_updates_existing():
    await svc.upsert_config(
        repo_url="https://github.com/owner/repo",
        auth_mode="pat_https",
        auth_secret_ref="ref1",
        branch="main",
        commit_author_name="bot",
        commit_author_email="bot@local",
        excluded_columns={},
        selected_tables=["t1"],
        cron_expr=None,
        cron_enabled=False,
    )
    updated = await svc.upsert_config(
        repo_url="https://github.com/owner/repo",
        auth_mode="ssh_key",
        auth_secret_ref="ref2",
        branch="develop",
        commit_author_name="bot",
        commit_author_email="bot@local",
        excluded_columns={},
        selected_tables=["t1", "t2"],
        cron_expr="0 4 * * *",
        cron_enabled=True,
    )
    assert updated.auth_mode == "ssh_key"
    assert updated.branch == "develop"
    assert updated.selected_tables == ["t1", "t2"]
    assert updated.cron_expr == "0 4 * * *"
    assert updated.cron_enabled is True


async def test_delete_config_removes_singleton():
    await svc.upsert_config(
        repo_url="url", auth_mode="pat_https", auth_secret_ref="ref",
        branch="main", commit_author_name="b", commit_author_email="b@l",
        excluded_columns={}, selected_tables=["t1"],
        cron_expr=None, cron_enabled=False,
    )
    await svc.delete_config()
    assert await svc.get_config() is None


async def test_list_available_tables_returns_public_tables(fresh_db):
    tables = await svc.list_available_tables()
    assert isinstance(tables, list)
    assert "git_sync_config" in tables
    assert "users" in tables
    assert tables == sorted(tables)


async def test_record_export_run_ok():
    await svc.upsert_config(
        repo_url="url", auth_mode="pat_https", auth_secret_ref="ref",
        branch="main", commit_author_name="b", commit_author_email="b@l",
        excluded_columns={}, selected_tables=["t1"],
        cron_expr=None, cron_enabled=False,
    )
    await svc.record_export_run(
        status="ok", sha="abc123", error=None, tables_count=5,
    )
    config = await svc.get_config()
    assert config.last_export_status == "ok"
    assert config.last_export_sha == "abc123"
    assert config.last_export_tables_count == 5
    assert config.last_export_error is None
    assert config.last_export_at is not None


async def test_record_export_run_failed():
    await svc.upsert_config(
        repo_url="url", auth_mode="pat_https", auth_secret_ref="ref",
        branch="main", commit_author_name="b", commit_author_email="b@l",
        excluded_columns={}, selected_tables=["t1"],
        cron_expr=None, cron_enabled=False,
    )
    await svc.record_export_run(
        status="failed", sha=None, error="GitAuthError: 401", tables_count=None,
    )
    config = await svc.get_config()
    assert config.last_export_status == "failed"
    assert config.last_export_error == "GitAuthError: 401"
    assert config.last_export_sha is None


async def test_record_import_run_ok():
    await svc.upsert_config(
        repo_url="url", auth_mode="pat_https", auth_secret_ref="ref",
        branch="main", commit_author_name="b", commit_author_email="b@l",
        excluded_columns={}, selected_tables=["t1"],
        cron_expr=None, cron_enabled=False,
    )
    await svc.record_import_run(
        status="ok", error=None,
        rows_inserted=10, rows_updated=5, rows_deleted=2,
    )
    config = await svc.get_config()
    assert config.last_import_status == "ok"
    assert config.last_import_rows_inserted == 10
    assert config.last_import_rows_updated == 5
    assert config.last_import_rows_deleted == 2
```

### Step 2 — Vérifier l'échec

- [ ] Lancer : `cd backend && uv run pytest tests/services/test_git_sync_service.py -v`
- [ ] Attendu : ModuleNotFoundError pour `agflow.services.git_sync_service`.

### Step 3 — Écrire le service

- [ ] Créer `backend/src/agflow/services/git_sync_service.py` :

```python
"""CRUD config singleton git_sync_config + utilitaires DB."""
from __future__ import annotations

import json
from typing import Any

import structlog

from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.schemas.git_sync import GitSyncConfigDTO

_log = structlog.get_logger(__name__)


def _row_to_dto(row: dict[str, Any]) -> GitSyncConfigDTO:
    """Convertit une row asyncpg en GitSyncConfigDTO (parse JSONB → dict/list)."""
    excluded = row["excluded_columns"]
    if isinstance(excluded, str):
        excluded = json.loads(excluded)
    selected = row["selected_tables"]
    if isinstance(selected, str):
        selected = json.loads(selected)
    return GitSyncConfigDTO(
        repo_url=row["repo_url"],
        auth_mode=row["auth_mode"],
        auth_secret_ref=row["auth_secret_ref"],
        branch=row["branch"],
        commit_author_name=row["commit_author_name"],
        commit_author_email=row["commit_author_email"],
        excluded_columns=excluded,
        selected_tables=selected,
        cron_expr=row["cron_expr"],
        cron_enabled=row["cron_enabled"],
        last_export_at=row["last_export_at"],
        last_export_status=row["last_export_status"],
        last_export_sha=row["last_export_sha"],
        last_export_error=row["last_export_error"],
        last_export_tables_count=row["last_export_tables_count"],
        last_import_at=row["last_import_at"],
        last_import_status=row["last_import_status"],
        last_import_error=row["last_import_error"],
        last_import_rows_inserted=row["last_import_rows_inserted"],
        last_import_rows_updated=row["last_import_rows_updated"],
        last_import_rows_deleted=row["last_import_rows_deleted"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def get_config() -> GitSyncConfigDTO | None:
    """Lit la config singleton. None si la table est vide."""
    row = await fetch_one("SELECT * FROM git_sync_config WHERE id = 1")
    return _row_to_dto(row) if row else None


async def upsert_config(
    *,
    repo_url: str,
    auth_mode: str,
    auth_secret_ref: str,
    branch: str,
    commit_author_name: str,
    commit_author_email: str,
    excluded_columns: dict[str, list[str]],
    selected_tables: list[str],
    cron_expr: str | None,
    cron_enabled: bool,
) -> GitSyncConfigDTO:
    """INSERT (1) ON CONFLICT (id) DO UPDATE — préserve les last_* existants."""
    await execute(
        """
        INSERT INTO git_sync_config (
            id, repo_url, auth_mode, auth_secret_ref,
            branch, commit_author_name, commit_author_email,
            excluded_columns, selected_tables,
            cron_expr, cron_enabled
        )
        VALUES (1, $1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb, $9, $10)
        ON CONFLICT (id) DO UPDATE SET
            repo_url             = EXCLUDED.repo_url,
            auth_mode            = EXCLUDED.auth_mode,
            auth_secret_ref      = EXCLUDED.auth_secret_ref,
            branch               = EXCLUDED.branch,
            commit_author_name   = EXCLUDED.commit_author_name,
            commit_author_email  = EXCLUDED.commit_author_email,
            excluded_columns     = EXCLUDED.excluded_columns,
            selected_tables      = EXCLUDED.selected_tables,
            cron_expr            = EXCLUDED.cron_expr,
            cron_enabled         = EXCLUDED.cron_enabled
        """,
        repo_url, auth_mode, auth_secret_ref,
        branch, commit_author_name, commit_author_email,
        json.dumps(excluded_columns), json.dumps(selected_tables),
        cron_expr, cron_enabled,
    )
    _log.info("git_sync.config.upserted", repo_url=repo_url, branch=branch)
    config = await get_config()
    assert config is not None
    return config


async def delete_config() -> None:
    """Supprime la ligne singleton (réinit complète)."""
    await execute("DELETE FROM git_sync_config WHERE id = 1")
    _log.info("git_sync.config.deleted")


async def list_available_tables() -> list[str]:
    """Liste les tables du schéma public, triées alphabétiquement."""
    rows = await fetch_all(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        ORDER BY table_name
        """
    )
    return [r["table_name"] for r in rows]


async def record_export_run(
    *,
    status: str,
    sha: str | None,
    error: str | None,
    tables_count: int | None,
) -> None:
    """Met à jour les colonnes last_export_*."""
    await execute(
        """
        UPDATE git_sync_config
        SET last_export_at = now(),
            last_export_status = $1,
            last_export_sha = $2,
            last_export_error = $3,
            last_export_tables_count = $4
        WHERE id = 1
        """,
        status, sha, error, tables_count,
    )


async def record_import_run(
    *,
    status: str,
    error: str | None,
    rows_inserted: int | None,
    rows_updated: int | None,
    rows_deleted: int | None,
) -> None:
    """Met à jour les colonnes last_import_*."""
    await execute(
        """
        UPDATE git_sync_config
        SET last_import_at = now(),
            last_import_status = $1,
            last_import_error = $2,
            last_import_rows_inserted = $3,
            last_import_rows_updated = $4,
            last_import_rows_deleted = $5
        WHERE id = 1
        """,
        status, error, rows_inserted, rows_updated, rows_deleted,
    )
```

### Step 4 — Lancer les tests (passing)

- [ ] Lancer : `cd backend && uv run pytest tests/services/test_git_sync_service.py -v`
- [ ] Attendu : 8 tests PASSED. **DONE_WITH_CONCERNS acceptable si Postgres LXC injoignable depuis Windows** (validation E2E à T11).

### Step 5 — Lint

- [ ] Lancer : `cd backend && uv run ruff check src/agflow/services/git_sync_service.py tests/services/test_git_sync_service.py`
- [ ] Attendu : All checks passed.

### Step 6 — Commit

- [ ] Lancer :

```bash
git add backend/src/agflow/services/git_sync_service.py backend/tests/services/test_git_sync_service.py
git commit -m "feat(git-sync-service): CRUD config singleton + list_available_tables + record_*_run"
```

---

## Tâche 3 — Service git_sync_github_client (parse_repo_url + list_commits)

**Files:**
- Create: `backend/src/agflow/services/git_sync_github_client.py`
- Test: `backend/tests/services/test_git_sync_github_client.py`

### Step 1 — Écrire les tests (failing)

- [ ] Créer `backend/tests/services/test_git_sync_github_client.py` :

```python
"""Tests du github_client : parse_repo_url + list_commits (mock httpx)."""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from agflow.services import git_sync_github_client as gh

pytestmark = pytest.mark.asyncio


# ─── parse_repo_url ─────────────────────────────────────────────────────

def test_parse_https_url():
    parsed = gh.parse_repo_url("https://github.com/gaelgael5/agflow-sync")
    assert parsed.host == "github.com"
    assert parsed.owner == "gaelgael5"
    assert parsed.repo == "agflow-sync"


def test_parse_https_url_with_git_suffix():
    parsed = gh.parse_repo_url("https://github.com/gaelgael5/agflow-sync.git")
    assert parsed.repo == "agflow-sync"


def test_parse_ssh_url():
    parsed = gh.parse_repo_url("git@github.com:gaelgael5/agflow-sync.git")
    assert parsed.host == "github.com"
    assert parsed.owner == "gaelgael5"
    assert parsed.repo == "agflow-sync"


def test_parse_unsupported_host():
    with pytest.raises(gh.UnsupportedHostError):
        gh.list_commits_unsupported_check("https://gitlab.com/owner/repo")


# ─── list_commits (mocked httpx) ────────────────────────────────────────

async def test_list_commits_returns_parsed_data(monkeypatch):
    payload = [
        {
            "sha": "abc1234567890",
            "commit": {
                "message": "feat: hello",
                "author": {
                    "name": "Alice",
                    "email": "alice@example.com",
                    "date": "2026-05-17T10:00:00Z",
                },
            },
            "html_url": "https://github.com/owner/repo/commit/abc1234567890",
        }
    ]

    class _MockClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, **kw):
            return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "AsyncClient", _MockClient)
    commits = await gh.list_commits(
        repo_url="https://github.com/owner/repo",
        branch="main",
        limit=10,
    )
    assert len(commits) == 1
    assert commits[0].sha == "abc1234567890"
    assert commits[0].short_sha == "abc1234"
    assert commits[0].author_name == "Alice"
    assert commits[0].html_url == "https://github.com/owner/repo/commit/abc1234567890"


async def test_list_commits_raises_on_404(monkeypatch):
    class _MockClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def get(self, url, **kw):
            return httpx.Response(404, json={"message": "Not Found"},
                                  request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "AsyncClient", _MockClient)
    with pytest.raises(httpx.HTTPStatusError):
        await gh.list_commits(
            repo_url="https://github.com/owner/repo",
            branch="main",
        )


async def test_list_commits_raises_unsupported_for_gitlab():
    with pytest.raises(gh.UnsupportedHostError):
        await gh.list_commits(
            repo_url="https://gitlab.com/owner/repo",
            branch="main",
        )
```

### Step 2 — Vérifier l'échec

- [ ] Lancer : `cd backend && uv run pytest tests/services/test_git_sync_github_client.py -v`
- [ ] Attendu : ModuleNotFoundError.

### Step 3 — Écrire le service

- [ ] Créer `backend/src/agflow/services/git_sync_github_client.py` :

```python
"""Client minimal pour l'API GitHub : parse + list_commits."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

import httpx
import structlog

_log = structlog.get_logger(__name__)

_SSH_RE = re.compile(r"^git@([^:]+):([^/]+)/(.+?)(?:\.git)?$")
_TIMEOUT = httpx.Timeout(10.0)


class UnsupportedHostError(Exception):
    """Host autre que github.com — listing commits non supporté."""


@dataclass(frozen=True)
class ParsedRepo:
    host: str
    owner: str
    repo: str


@dataclass(frozen=True)
class GitCommit:
    sha: str
    short_sha: str
    message: str
    author_name: str
    author_email: str
    authored_at: datetime
    html_url: str


def parse_repo_url(repo_url: str) -> ParsedRepo:
    """Parse 'git@github.com:owner/repo.git' OU 'https://github.com/owner/repo(.git)'."""
    m = _SSH_RE.match(repo_url)
    if m is not None:
        host, owner, repo = m.group(1), m.group(2), m.group(3)
        if repo.endswith(".git"):
            repo = repo[:-4]
        return ParsedRepo(host=host, owner=owner, repo=repo)

    parsed = urlparse(repo_url)
    if not parsed.netloc or not parsed.path:
        raise ValueError(f"unparseable repo_url: {repo_url!r}")
    parts = parsed.path.strip("/").split("/")
    if len(parts) < 2:
        raise ValueError(f"unparseable repo_url: {repo_url!r}")
    owner, repo = parts[0], parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    return ParsedRepo(host=parsed.netloc, owner=owner, repo=repo)


def list_commits_unsupported_check(repo_url: str) -> None:
    """Lève UnsupportedHostError si l'URL ne pointe pas vers github.com."""
    parsed = parse_repo_url(repo_url)
    if parsed.host != "github.com":
        raise UnsupportedHostError(
            f"GitHub API listing not supported for host {parsed.host!r}"
        )


async def list_commits(
    *,
    repo_url: str,
    branch: str,
    limit: int = 30,
    auth_token: str | None = None,
) -> list[GitCommit]:
    """Liste les commits d'une branche via l'API GitHub.

    Lève UnsupportedHostError si host != github.com.
    Lève httpx.HTTPStatusError pour les 4xx/5xx.
    """
    list_commits_unsupported_check(repo_url)
    parsed = parse_repo_url(repo_url)
    url = f"https://api.github.com/repos/{parsed.owner}/{parsed.repo}/commits"
    params = {"sha": branch, "per_page": str(limit)}
    headers = {"Accept": "application/vnd.github+json"}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    _log.info(
        "git_sync.github.list_commits",
        owner=parsed.owner, repo=parsed.repo, branch=branch, limit=limit,
    )
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(url, params=params, headers=headers)
    resp.raise_for_status()

    out: list[GitCommit] = []
    for item in resp.json():
        sha = item["sha"]
        commit = item["commit"]
        author = commit.get("author") or {}
        out.append(
            GitCommit(
                sha=sha,
                short_sha=sha[:7],
                message=commit.get("message", ""),
                author_name=author.get("name", ""),
                author_email=author.get("email", ""),
                authored_at=datetime.fromisoformat(
                    author.get("date", "1970-01-01T00:00:00Z").replace("Z", "+00:00")
                ),
                html_url=item.get("html_url", ""),
            )
        )
    return out
```

### Step 4 — Lancer les tests (passing)

- [ ] Lancer : `cd backend && uv run pytest tests/services/test_git_sync_github_client.py -v`
- [ ] Attendu : 7 tests PASSED.

### Step 5 — Lint

- [ ] Lancer : `cd backend && uv run ruff check src/agflow/services/git_sync_github_client.py tests/services/test_git_sync_github_client.py`

### Step 6 — Commit

- [ ] Lancer :

```bash
git add backend/src/agflow/services/git_sync_github_client.py backend/tests/services/test_git_sync_github_client.py
git commit -m "feat(git-sync-service): github_client (parse_repo_url + list_commits)"
```

---

## Tâche 4 — Service git_sync_runner (wrappers SDK)

**Files:**
- Create: `backend/src/agflow/services/git_sync_runner.py`
- Test: `backend/tests/services/test_git_sync_runner.py`

### Step 1 — Écrire les tests (failing)

- [ ] Créer `backend/tests/services/test_git_sync_runner.py` :

```python
"""Tests du runner : wrappers SDK ExportService / ImportService."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agflow.services import git_sync_runner

pytestmark = pytest.mark.asyncio


@pytest.fixture
def fake_config():
    from agflow.schemas.git_sync import GitSyncConfigDTO
    from datetime import datetime

    return GitSyncConfigDTO(
        repo_url="https://github.com/owner/repo",
        auth_mode="pat_https",
        auth_secret_ref="${vault://default:git/pat}",
        branch="main",
        commit_author_name="bot",
        commit_author_email="bot@local",
        excluded_columns={"users": ["password_hash"]},
        selected_tables=["infra_categories", "infra_named_types"],
        cron_expr=None,
        cron_enabled=False,
        last_export_at=None, last_export_status=None, last_export_sha=None,
        last_export_error=None, last_export_tables_count=None,
        last_import_at=None, last_import_status=None, last_import_error=None,
        last_import_rows_inserted=None, last_import_rows_updated=None,
        last_import_rows_deleted=None,
        created_at=datetime(2026, 5, 17), updated_at=datetime(2026, 5, 17),
    )


async def test_run_export_happy_path(fake_config):
    from sdk.git_sync import SyncResult, TableRef

    sync_result = SyncResult(
        success=True,
        commit_sha="abc1234",
        tables_exported=[
            TableRef(schema="public", table="infra_categories"),
            TableRef(schema="public", table="infra_named_types"),
        ],
    )

    with patch.object(git_sync_runner, "get_config", AsyncMock(return_value=fake_config)), \
         patch.object(git_sync_runner.vault_client, "resolve_ref", AsyncMock(return_value="literal-token")), \
         patch.object(git_sync_runner, "_build_export_service", return_value=MagicMock(
            export=AsyncMock(return_value=sync_result))), \
         patch.object(git_sync_runner.svc, "record_export_run", AsyncMock()) as rec:
        result = await git_sync_runner.run_export()

    assert result.sha == "abc1234"
    assert result.tables_count == 2
    rec.assert_called_once_with(
        status="ok", sha="abc1234", error=None, tables_count=2,
    )


async def test_run_export_failed_records_failure(fake_config):
    with patch.object(git_sync_runner, "get_config", AsyncMock(return_value=fake_config)), \
         patch.object(git_sync_runner.vault_client, "resolve_ref", AsyncMock(return_value="literal-token")), \
         patch.object(git_sync_runner, "_build_export_service", side_effect=RuntimeError("boom")), \
         patch.object(git_sync_runner.svc, "record_export_run", AsyncMock()) as rec:
        with pytest.raises(RuntimeError, match="boom"):
            await git_sync_runner.run_export()

    rec.assert_called_once()
    kwargs = rec.call_args.kwargs
    assert kwargs["status"] == "failed"
    assert "boom" in kwargs["error"]


async def test_run_export_no_config_raises():
    with patch.object(git_sync_runner, "get_config", AsyncMock(return_value=None)):
        with pytest.raises(git_sync_runner.GitSyncNotConfiguredError):
            await git_sync_runner.run_export()


async def test_run_preview_happy_path(fake_config):
    from sdk.git_sync import ImportPreview, TablePreview, TableRef

    preview = ImportPreview(tables=[
        TablePreview(
            table=TableRef(schema="public", table="infra_categories"),
            to_insert=3, to_update=1, to_delete=0,
        ),
    ])

    with patch.object(git_sync_runner, "get_config", AsyncMock(return_value=fake_config)), \
         patch.object(git_sync_runner.vault_client, "resolve_ref", AsyncMock(return_value="literal-token")), \
         patch.object(git_sync_runner, "_build_import_service", return_value=MagicMock(
            preview=AsyncMock(return_value=preview))):
        result = await git_sync_runner.run_preview()

    assert len(result.tables) == 1
    assert result.tables[0].table == "public.infra_categories"
    assert result.tables[0].to_insert == 3


async def test_run_import_happy_path(fake_config):
    from sdk.git_sync import ImportResult, TableRef

    sdk_result = ImportResult(
        success=True,
        tables_processed=[TableRef(schema="public", table="infra_categories")],
        rows_inserted={"public.infra_categories": 3},
        rows_updated={"public.infra_categories": 1},
        rows_deleted={"public.infra_categories": 0},
    )

    with patch.object(git_sync_runner, "get_config", AsyncMock(return_value=fake_config)), \
         patch.object(git_sync_runner.vault_client, "resolve_ref", AsyncMock(return_value="literal-token")), \
         patch.object(git_sync_runner, "_build_import_service", return_value=MagicMock(
            import_=AsyncMock(return_value=sdk_result))), \
         patch.object(git_sync_runner.svc, "record_import_run", AsyncMock()) as rec:
        result = await git_sync_runner.run_import()

    assert result.rows_inserted == 3
    assert result.rows_updated == 1
    assert result.rows_deleted == 0
    rec.assert_called_once_with(
        status="ok", error=None,
        rows_inserted=3, rows_updated=1, rows_deleted=0,
    )


async def test_test_secret_ref_ok():
    with patch.object(git_sync_runner.vault_client, "resolve_ref", AsyncMock(return_value="resolved")):
        result = await git_sync_runner.test_secret_ref("${vault://default:git/pat}")
    assert result.ok is True
    assert result.error is None


async def test_test_secret_ref_ko():
    with patch.object(git_sync_runner.vault_client, "resolve_ref",
                       AsyncMock(side_effect=Exception("secret not found"))):
        result = await git_sync_runner.test_secret_ref("${vault://default:git/missing}")
    assert result.ok is False
    assert "secret not found" in result.error
```

### Step 2 — Vérifier l'échec

- [ ] Lancer : `cd backend && uv run pytest tests/services/test_git_sync_runner.py -v`
- [ ] Attendu : ModuleNotFoundError.

### Step 3 — Écrire le runner

- [ ] Créer `backend/src/agflow/services/git_sync_runner.py` :

```python
"""Wrappers du SDK Git Sync : run_export / run_preview / run_import / test_secret_ref.

Le runner :
  1. lit la config singleton via git_sync_service
  2. résout auth_secret_ref via vault_client (Harpocrate)
  3. construit GitConfig + GitService + Export/ImportService du SDK
  4. délègue l'exécution, capture les exceptions
  5. enregistre le résultat via record_*_run
"""
from __future__ import annotations

from typing import Any

import structlog

from agflow.db.pool import get_pool
from agflow.schemas.git_sync import (
    GitSyncExportResult,
    GitSyncImportPreviewResult,
    GitSyncImportResult,
    GitSyncTablePreview,
    GitSyncTestSecretRefResult,
)
from agflow.services import git_sync_service as svc
from agflow.services import vault_client
from sdk.git_sync import (
    AuthMode,
    ExportService,
    GitConfig,
    GitService,
    ImportService,
    TableRef,
)

_log = structlog.get_logger(__name__)

_MODULE_NAME = "docker"  # spec SDK §2 — un seul module pour agflow.docker


class GitSyncNotConfiguredError(Exception):
    """Aucune config singleton en DB."""


class _ResolvedVaultClient:
    """Wrapper trivial : la valeur est déjà résolue par le runner, le SDK
    ne devrait jamais appeler .get() puisqu'on lui passe une valeur littérale."""

    def __init__(self, resolved_value: str) -> None:
        self._value = resolved_value

    def get(self, name: str) -> str:
        # Si jamais le SDK essaie de résoudre, on retourne la valeur (compat
        # défensive — ne devrait jamais arriver vu qu'on passe du littéral).
        return self._value


async def _build_git_config(config_dto, resolved_auth: str) -> GitConfig:
    return GitConfig(
        repo_url=config_dto.repo_url,
        auth_mode=AuthMode(config_dto.auth_mode),
        auth_secret_ref=resolved_auth,  # littéral — VaultResolver le retourne tel quel
        module_name=_MODULE_NAME,
        commit_author_name=config_dto.commit_author_name,
        commit_author_email=config_dto.commit_author_email,
        branch=config_dto.branch,
        excluded_columns=config_dto.excluded_columns,
    )


def _build_export_service(db_conn: Any, git_service: GitService) -> ExportService:
    return ExportService(db_conn, git_service)


def _build_import_service(db_conn: Any, git_service: GitService) -> ImportService:
    return ImportService(db_conn, git_service)


def _selected_tables_to_refs(selected: list[str]) -> list[TableRef]:
    """`['users', 'public.infra']` → list of TableRef."""
    out: list[TableRef] = []
    for name in selected:
        if "." in name:
            schema, table = name.split(".", 1)
        else:
            schema, table = "public", name
        out.append(TableRef(schema=schema, table=table))
    return out


async def get_config():
    """Indirection pour faciliter le mock dans les tests."""
    return await svc.get_config()


async def run_export() -> GitSyncExportResult:
    """Délègue à ExportService.export(). Met à jour last_export_*."""
    config = await get_config()
    if config is None:
        raise GitSyncNotConfiguredError("git_sync_config is empty — configure first")
    if not config.selected_tables:
        raise ValueError("selected_tables is empty — nothing to export")

    try:
        resolved = await vault_client.resolve_ref(config.auth_secret_ref)
        git_config = await _build_git_config(config, resolved)
        git_service = GitService(git_config, _ResolvedVaultClient(resolved))
        tables = _selected_tables_to_refs(config.selected_tables)
        async with (await get_pool()).acquire() as conn:
            export_svc = _build_export_service(conn, git_service)
            sync_result = await export_svc.export(tables)
    except Exception as exc:
        await svc.record_export_run(
            status="failed", sha=None,
            error=f"{type(exc).__name__}: {exc}",
            tables_count=None,
        )
        raise

    await svc.record_export_run(
        status="ok",
        sha=sync_result.commit_sha,
        error=None,
        tables_count=len(sync_result.tables_exported),
    )
    return GitSyncExportResult(
        sha=sync_result.commit_sha or "",
        tables_count=len(sync_result.tables_exported),
    )


async def run_preview() -> GitSyncImportPreviewResult:
    """Délègue à ImportService.preview(). Pas d'écriture DB persistante."""
    config = await get_config()
    if config is None:
        raise GitSyncNotConfiguredError("git_sync_config is empty — configure first")

    resolved = await vault_client.resolve_ref(config.auth_secret_ref)
    git_config = await _build_git_config(config, resolved)
    git_service = GitService(git_config, _ResolvedVaultClient(resolved))
    tables = _selected_tables_to_refs(config.selected_tables) if config.selected_tables else None
    async with (await get_pool()).acquire() as conn:
        import_svc = _build_import_service(conn, git_service)
        preview = await import_svc.preview(tables)

    return GitSyncImportPreviewResult(
        tables=[
            GitSyncTablePreview(
                table=p.table.full_name,
                to_insert=p.to_insert,
                to_update=p.to_update,
                to_delete=p.to_delete,
            )
            for p in preview.tables
        ]
    )


async def run_import() -> GitSyncImportResult:
    """Délègue à ImportService.import_(). Met à jour last_import_*."""
    config = await get_config()
    if config is None:
        raise GitSyncNotConfiguredError("git_sync_config is empty — configure first")

    try:
        resolved = await vault_client.resolve_ref(config.auth_secret_ref)
        git_config = await _build_git_config(config, resolved)
        git_service = GitService(git_config, _ResolvedVaultClient(resolved))
        tables = _selected_tables_to_refs(config.selected_tables) if config.selected_tables else None
        async with (await get_pool()).acquire() as conn:
            import_svc = _build_import_service(conn, git_service)
            sdk_result = await import_svc.import_(tables)
    except Exception as exc:
        await svc.record_import_run(
            status="failed", error=f"{type(exc).__name__}: {exc}",
            rows_inserted=None, rows_updated=None, rows_deleted=None,
        )
        raise

    total_ins = sum(sdk_result.rows_inserted.values())
    total_upd = sum(sdk_result.rows_updated.values())
    total_del = sum(sdk_result.rows_deleted.values())
    await svc.record_import_run(
        status="ok", error=None,
        rows_inserted=total_ins, rows_updated=total_upd, rows_deleted=total_del,
    )
    return GitSyncImportResult(
        rows_inserted=total_ins,
        rows_updated=total_upd,
        rows_deleted=total_del,
    )


async def test_secret_ref(auth_secret_ref: str) -> GitSyncTestSecretRefResult:
    """Essaie de résoudre la ref Harpocrate, sans rien stocker.

    Retourne ok=True si vault_client.resolve_ref() renvoie une valeur sans
    exception. Le contenu du secret n'est PAS retourné — juste un booléen.
    """
    try:
        await vault_client.resolve_ref(auth_secret_ref)
    except Exception as exc:
        return GitSyncTestSecretRefResult(
            ok=False, error=f"{type(exc).__name__}: {exc}",
        )
    return GitSyncTestSecretRefResult(ok=True)
```

### Step 4 — Lancer les tests (passing)

- [ ] Lancer : `cd backend && uv run pytest tests/services/test_git_sync_runner.py -v`
- [ ] Attendu : 7 tests PASSED.

### Step 5 — Lint

- [ ] Lancer : `cd backend && uv run ruff check src/agflow/services/git_sync_runner.py tests/services/test_git_sync_runner.py`

### Step 6 — Commit

- [ ] Lancer :

```bash
git add backend/src/agflow/services/git_sync_runner.py backend/tests/services/test_git_sync_runner.py
git commit -m "feat(git-sync-service): runner (wrappers SDK export/preview/import + test_secret_ref)"
```

---

## Tâche 5 — Worker git_sync_scheduler (APScheduler dédié)

**Files:**
- Create: `backend/src/agflow/services/git_sync_scheduler.py`
- Test: `backend/tests/services/test_git_sync_scheduler.py`

### Step 1 — Écrire les tests (failing)

- [ ] Créer `backend/tests/services/test_git_sync_scheduler.py` :

```python
"""Tests du git_sync_scheduler (APScheduler wrapper)."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agflow.services import git_sync_scheduler

pytestmark = pytest.mark.asyncio


def _fake_config(*, cron_expr=None, cron_enabled=False):
    from agflow.schemas.git_sync import GitSyncConfigDTO
    return GitSyncConfigDTO(
        repo_url="url", auth_mode="pat_https", auth_secret_ref="ref",
        branch="main", commit_author_name="b", commit_author_email="b@l",
        excluded_columns={}, selected_tables=["t"],
        cron_expr=cron_expr, cron_enabled=cron_enabled,
        last_export_at=None, last_export_status=None, last_export_sha=None,
        last_export_error=None, last_export_tables_count=None,
        last_import_at=None, last_import_status=None, last_import_error=None,
        last_import_rows_inserted=None, last_import_rows_updated=None,
        last_import_rows_deleted=None,
        created_at=datetime(2026, 5, 17), updated_at=datetime(2026, 5, 17),
    )


async def test_start_then_stop_lifecycle():
    await git_sync_scheduler.start()
    assert git_sync_scheduler._scheduler is not None
    assert git_sync_scheduler._scheduler.running is True
    await git_sync_scheduler.stop()
    assert git_sync_scheduler._scheduler is None


async def test_reload_adds_export_job_when_cron_enabled():
    await git_sync_scheduler.start()
    try:
        with patch.object(git_sync_scheduler, "get_config",
                           AsyncMock(return_value=_fake_config(
                               cron_expr="0 4 * * *", cron_enabled=True))):
            await git_sync_scheduler.reload_schedule()
        assert git_sync_scheduler._scheduler.get_job("export") is not None
    finally:
        await git_sync_scheduler.stop()


async def test_reload_removes_export_job_when_disabled():
    await git_sync_scheduler.start()
    try:
        with patch.object(git_sync_scheduler, "get_config",
                           AsyncMock(return_value=_fake_config(
                               cron_expr="0 4 * * *", cron_enabled=True))):
            await git_sync_scheduler.reload_schedule()
        assert git_sync_scheduler._scheduler.get_job("export") is not None

        with patch.object(git_sync_scheduler, "get_config",
                           AsyncMock(return_value=_fake_config(
                               cron_expr="0 4 * * *", cron_enabled=False))):
            await git_sync_scheduler.reload_schedule()
        assert git_sync_scheduler._scheduler.get_job("export") is None
    finally:
        await git_sync_scheduler.stop()


async def test_reload_removes_job_when_no_config():
    await git_sync_scheduler.start()
    try:
        with patch.object(git_sync_scheduler, "get_config",
                           AsyncMock(return_value=_fake_config(
                               cron_expr="0 4 * * *", cron_enabled=True))):
            await git_sync_scheduler.reload_schedule()
        assert git_sync_scheduler._scheduler.get_job("export") is not None

        with patch.object(git_sync_scheduler, "get_config", AsyncMock(return_value=None)):
            await git_sync_scheduler.reload_schedule()
        assert git_sync_scheduler._scheduler.get_job("export") is None
    finally:
        await git_sync_scheduler.stop()


async def test_trigger_now_adds_date_trigger_job():
    await git_sync_scheduler.start()
    try:
        with patch.object(git_sync_scheduler, "run_export", AsyncMock()):
            await git_sync_scheduler.trigger_now()
        jobs = git_sync_scheduler._scheduler.get_jobs()
        assert any(j.id.startswith("trigger-now:") for j in jobs)
    finally:
        await git_sync_scheduler.stop()
```

### Step 2 — Vérifier l'échec

- [ ] Lancer : `cd backend && uv run pytest tests/services/test_git_sync_scheduler.py -v`
- [ ] Attendu : ModuleNotFoundError.

### Step 3 — Écrire le scheduler

- [ ] Créer `backend/src/agflow/services/git_sync_scheduler.py` :

```python
"""AsyncIOScheduler dédié pour Git Sync (séparé de backup_scheduler).

Jobs gérés :
  - "export"        : cron user-defined (config.cron_expr) si cron_enabled
  - "__resync__"    : tick interne 30s qui appelle reload_schedule()
  - "trigger-now:*" : jobs DateTrigger(now) pour les bouton "Run now"
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from agflow.services import git_sync_service as svc
from agflow.services.git_sync_runner import run_export

_log = structlog.get_logger(__name__)

_RESYNC_INTERVAL_SECONDS = 30
_scheduler: AsyncIOScheduler | None = None


async def get_config():
    """Indirection pour faciliter le mock dans les tests."""
    return await svc.get_config()


async def start() -> None:
    """Démarre le scheduler et installe le tick __resync__."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        _resync_tick,
        IntervalTrigger(seconds=_RESYNC_INTERVAL_SECONDS),
        id="__resync__",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    _scheduler.start()
    await reload_schedule()
    _log.info("git_sync.scheduler.started")


async def stop() -> None:
    """Arrête proprement le scheduler."""
    global _scheduler
    if _scheduler is None:
        return
    _scheduler.shutdown(wait=True)
    _scheduler = None
    _log.info("git_sync.scheduler.stopped")


async def reload_schedule() -> None:
    """Relit la config et synchronise le job 'export'."""
    if _scheduler is None:
        return
    config = await get_config()
    existing = _scheduler.get_job("export")

    if config is None or not config.cron_enabled or not config.cron_expr:
        if existing is not None:
            _scheduler.remove_job("export")
            _log.info("git_sync.scheduler.export_job_removed")
        return

    try:
        trigger = CronTrigger.from_crontab(config.cron_expr)
    except ValueError:
        _log.warning("git_sync.scheduler.invalid_cron", cron_expr=config.cron_expr)
        if existing is not None:
            _scheduler.remove_job("export")
        return

    _scheduler.add_job(
        _safe_run_export,
        trigger,
        id="export",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    _log.info("git_sync.scheduler.export_job_set", cron_expr=config.cron_expr)


async def trigger_now() -> None:
    """Déclenche un export immédiat (job DateTrigger one-shot)."""
    if _scheduler is None:
        raise RuntimeError("scheduler not started")
    job_id = f"trigger-now:{uuid.uuid4()}"
    _scheduler.add_job(
        _safe_run_export,
        DateTrigger(run_date=datetime.now() + timedelta(seconds=1)),
        id=job_id,
        max_instances=1,
        coalesce=True,
    )
    _log.info("git_sync.scheduler.trigger_now", job_id=job_id)


async def _resync_tick() -> None:
    """Appelé toutes les _RESYNC_INTERVAL_SECONDS — relit la config."""
    try:
        await reload_schedule()
    except Exception as exc:
        _log.warning("git_sync.scheduler.resync_failed", error=str(exc))


async def _safe_run_export() -> None:
    """Wrapper qui catch tout (sinon APScheduler stoppe le job)."""
    try:
        await run_export()
    except Exception as exc:
        _log.warning("git_sync.scheduler.export_job_failed", error=str(exc))
```

### Step 4 — Lancer les tests (passing)

- [ ] Lancer : `cd backend && uv run pytest tests/services/test_git_sync_scheduler.py -v`
- [ ] Attendu : 5 tests PASSED.

### Step 5 — Lint

- [ ] Lancer : `cd backend && uv run ruff check src/agflow/services/git_sync_scheduler.py tests/services/test_git_sync_scheduler.py`

### Step 6 — Commit

- [ ] Lancer :

```bash
git add backend/src/agflow/services/git_sync_scheduler.py backend/tests/services/test_git_sync_scheduler.py
git commit -m "feat(git-sync-scheduler): APScheduler dédié + tick reload 30s + trigger_now"
```

---

## Tâche 6 — 9 endpoints REST + branchement main.py

**Files:**
- Create: `backend/src/agflow/api/admin/git_sync.py`
- Modify: `backend/src/agflow/main.py` (lifespan + include_router)
- Test: `backend/tests/api/test_admin_git_sync.py`

### Step 1 — Écrire les tests (failing)

- [ ] Créer `backend/tests/api/test_admin_git_sync.py` :

```python
"""Tests HTTP des 9 endpoints /api/admin/git-sync."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

pytestmark = pytest.mark.asyncio


@pytest.fixture
def _config_dto():
    from agflow.schemas.git_sync import GitSyncConfigDTO
    return GitSyncConfigDTO(
        repo_url="https://github.com/owner/repo",
        auth_mode="pat_https", auth_secret_ref="${vault://default:git/pat}",
        branch="main", commit_author_name="bot", commit_author_email="bot@local",
        excluded_columns={}, selected_tables=["users"],
        cron_expr=None, cron_enabled=False,
        last_export_at=None, last_export_status=None, last_export_sha=None,
        last_export_error=None, last_export_tables_count=None,
        last_import_at=None, last_import_status=None, last_import_error=None,
        last_import_rows_inserted=None, last_import_rows_updated=None,
        last_import_rows_deleted=None,
        created_at=datetime(2026, 5, 17), updated_at=datetime(2026, 5, 17),
    )


async def test_get_config_returns_404_when_empty(admin_client):
    with patch("agflow.api.admin.git_sync.svc.get_config", AsyncMock(return_value=None)):
        resp = await admin_client.get("/api/admin/git-sync/config")
    assert resp.status_code == 404


async def test_get_config_returns_200_when_set(admin_client, _config_dto):
    with patch("agflow.api.admin.git_sync.svc.get_config", AsyncMock(return_value=_config_dto)):
        resp = await admin_client.get("/api/admin/git-sync/config")
    assert resp.status_code == 200
    assert resp.json()["repo_url"] == "https://github.com/owner/repo"


async def test_put_config_upserts_and_reloads_scheduler(admin_client, _config_dto):
    with patch("agflow.api.admin.git_sync.svc.upsert_config",
                AsyncMock(return_value=_config_dto)) as up, \
         patch("agflow.api.admin.git_sync.git_sync_scheduler.reload_schedule",
                AsyncMock()) as rel:
        resp = await admin_client.put(
            "/api/admin/git-sync/config",
            json={
                "repo_url": "https://github.com/owner/repo",
                "auth_mode": "pat_https",
                "auth_secret_ref": "${vault://default:git/pat}",
                "branch": "main",
                "commit_author_name": "bot",
                "commit_author_email": "bot@local",
                "excluded_columns": {},
                "selected_tables": ["users"],
                "cron_expr": None,
                "cron_enabled": False,
            },
        )
    assert resp.status_code == 200
    up.assert_called_once()
    rel.assert_called_once()


async def test_put_config_rejects_invalid_cron(admin_client):
    resp = await admin_client.put(
        "/api/admin/git-sync/config",
        json={
            "repo_url": "https://github.com/owner/repo",
            "auth_mode": "pat_https",
            "auth_secret_ref": "ref",
            "branch": "main",
            "commit_author_name": "bot",
            "commit_author_email": "bot@local",
            "excluded_columns": {},
            "selected_tables": ["users"],
            "cron_expr": "not-a-cron",
            "cron_enabled": True,
        },
    )
    assert resp.status_code == 422


async def test_delete_config_returns_204(admin_client):
    with patch("agflow.api.admin.git_sync.svc.delete_config", AsyncMock()) as del_, \
         patch("agflow.api.admin.git_sync.git_sync_scheduler.reload_schedule", AsyncMock()):
        resp = await admin_client.delete("/api/admin/git-sync/config")
    assert resp.status_code == 204
    del_.assert_called_once()


async def test_get_available_tables(admin_client):
    with patch("agflow.api.admin.git_sync.svc.list_available_tables",
                AsyncMock(return_value=["users", "git_sync_config"])):
        resp = await admin_client.get("/api/admin/git-sync/available-tables")
    assert resp.status_code == 200
    assert resp.json() == ["users", "git_sync_config"]


async def test_post_test_secret_ref_ok(admin_client):
    from agflow.schemas.git_sync import GitSyncTestSecretRefResult
    with patch("agflow.api.admin.git_sync.git_sync_runner.test_secret_ref",
                AsyncMock(return_value=GitSyncTestSecretRefResult(ok=True))):
        resp = await admin_client.post(
            "/api/admin/git-sync/test-secret-ref",
            json={"auth_secret_ref": "${vault://default:git/pat}"},
        )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "error": None}


async def test_post_export(admin_client):
    from agflow.schemas.git_sync import GitSyncExportResult
    with patch("agflow.api.admin.git_sync.git_sync_runner.run_export",
                AsyncMock(return_value=GitSyncExportResult(sha="abc1234", tables_count=2))):
        resp = await admin_client.post("/api/admin/git-sync/export")
    assert resp.status_code == 200
    assert resp.json() == {"sha": "abc1234", "tables_count": 2}


async def test_post_preview_import(admin_client):
    from agflow.schemas.git_sync import GitSyncImportPreviewResult, GitSyncTablePreview
    payload = GitSyncImportPreviewResult(tables=[
        GitSyncTablePreview(table="public.users", to_insert=3, to_update=1, to_delete=0),
    ])
    with patch("agflow.api.admin.git_sync.git_sync_runner.run_preview",
                AsyncMock(return_value=payload)):
        resp = await admin_client.post("/api/admin/git-sync/preview-import")
    assert resp.status_code == 200
    body = resp.json()
    assert body["tables"][0]["table"] == "public.users"


async def test_post_import(admin_client):
    from agflow.schemas.git_sync import GitSyncImportResult
    with patch("agflow.api.admin.git_sync.git_sync_runner.run_import",
                AsyncMock(return_value=GitSyncImportResult(
                    rows_inserted=10, rows_updated=5, rows_deleted=2))):
        resp = await admin_client.post("/api/admin/git-sync/import")
    assert resp.status_code == 200
    assert resp.json() == {"rows_inserted": 10, "rows_updated": 5, "rows_deleted": 2}


async def test_get_commits_returns_list(admin_client, _config_dto):
    from agflow.services.git_sync_github_client import GitCommit
    commits = [
        GitCommit(
            sha="abc1234567890", short_sha="abc1234",
            message="feat: x", author_name="Alice", author_email="a@x.com",
            authored_at=datetime(2026, 5, 17), html_url="https://github.com/o/r/commit/abc1234",
        ),
    ]
    with patch("agflow.api.admin.git_sync.svc.get_config", AsyncMock(return_value=_config_dto)), \
         patch("agflow.api.admin.git_sync.gh.list_commits", AsyncMock(return_value=commits)):
        resp = await admin_client.get("/api/admin/git-sync/commits?limit=5")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["short_sha"] == "abc1234"


async def test_get_commits_unsupported_host(admin_client, _config_dto):
    from agflow.services.git_sync_github_client import UnsupportedHostError
    with patch("agflow.api.admin.git_sync.svc.get_config", AsyncMock(return_value=_config_dto)), \
         patch("agflow.api.admin.git_sync.gh.list_commits",
                AsyncMock(side_effect=UnsupportedHostError("gitlab.com"))):
        resp = await admin_client.get("/api/admin/git-sync/commits")
    assert resp.status_code == 422
```

### Step 2 — Vérifier l'échec

- [ ] Lancer : `cd backend && uv run pytest tests/api/test_admin_git_sync.py -v`
- [ ] Attendu : ModuleNotFoundError.

### Step 3 — Écrire l'API

- [ ] Créer `backend/src/agflow/api/admin/git_sync.py` :

```python
"""Endpoints REST /api/admin/git-sync."""
from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query

from agflow.auth.dependencies import require_admin
from agflow.schemas.git_sync import (
    GitSyncCommitDTO,
    GitSyncConfigDTO,
    GitSyncConfigUpsert,
    GitSyncExportResult,
    GitSyncImportPreviewResult,
    GitSyncImportResult,
    GitSyncTestSecretRefRequest,
    GitSyncTestSecretRefResult,
)
from agflow.services import git_sync_runner
from agflow.services import git_sync_scheduler
from agflow.services import git_sync_service as svc
from agflow.services import git_sync_github_client as gh

_log = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/admin/git-sync",
    tags=["admin", "git-sync"],
    dependencies=[Depends(require_admin)],
)


@router.get("/config", response_model=GitSyncConfigDTO)
async def get_config() -> GitSyncConfigDTO:
    config = await svc.get_config()
    if config is None:
        raise HTTPException(status_code=404, detail="Git sync not configured")
    return config


@router.put("/config", response_model=GitSyncConfigDTO)
async def put_config(body: GitSyncConfigUpsert) -> GitSyncConfigDTO:
    config = await svc.upsert_config(
        repo_url=body.repo_url,
        auth_mode=body.auth_mode,
        auth_secret_ref=body.auth_secret_ref,
        branch=body.branch,
        commit_author_name=body.commit_author_name,
        commit_author_email=body.commit_author_email,
        excluded_columns=body.excluded_columns,
        selected_tables=body.selected_tables,
        cron_expr=body.cron_expr,
        cron_enabled=body.cron_enabled,
    )
    await git_sync_scheduler.reload_schedule()
    return config


@router.delete("/config", status_code=204)
async def delete_config() -> None:
    await svc.delete_config()
    await git_sync_scheduler.reload_schedule()


@router.get("/available-tables", response_model=list[str])
async def get_available_tables() -> list[str]:
    return await svc.list_available_tables()


@router.post("/test-secret-ref", response_model=GitSyncTestSecretRefResult)
async def post_test_secret_ref(
    body: GitSyncTestSecretRefRequest,
) -> GitSyncTestSecretRefResult:
    return await git_sync_runner.test_secret_ref(body.auth_secret_ref)


@router.post("/export", response_model=GitSyncExportResult)
async def post_export() -> GitSyncExportResult:
    try:
        return await git_sync_runner.run_export()
    except git_sync_runner.GitSyncNotConfiguredError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        _log.warning("git_sync.api.export_failed", error=str(exc))
        raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}") from exc


@router.post("/preview-import", response_model=GitSyncImportPreviewResult)
async def post_preview_import() -> GitSyncImportPreviewResult:
    try:
        return await git_sync_runner.run_preview()
    except git_sync_runner.GitSyncNotConfiguredError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        _log.warning("git_sync.api.preview_failed", error=str(exc))
        raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}") from exc


@router.post("/import", response_model=GitSyncImportResult)
async def post_import() -> GitSyncImportResult:
    try:
        return await git_sync_runner.run_import()
    except git_sync_runner.GitSyncNotConfiguredError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        _log.warning("git_sync.api.import_failed", error=str(exc))
        raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}") from exc


@router.get("/commits", response_model=list[GitSyncCommitDTO])
async def get_commits(
    limit: int = Query(default=30, ge=1, le=100),
) -> list[GitSyncCommitDTO]:
    config = await svc.get_config()
    if config is None:
        raise HTTPException(status_code=404, detail="Git sync not configured")
    try:
        commits = await gh.list_commits(
            repo_url=config.repo_url,
            branch=config.branch,
            limit=limit,
        )
    except gh.UnsupportedHostError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        _log.warning("git_sync.api.commits_failed", error=str(exc))
        raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}") from exc

    return [
        GitSyncCommitDTO(
            sha=c.sha,
            short_sha=c.short_sha,
            message=c.message,
            author_name=c.author_name,
            author_email=c.author_email,
            authored_at=c.authored_at,
            html_url=c.html_url,
        )
        for c in commits
    ]
```

### Step 4 — Brancher dans main.py

- [ ] Vérifier d'abord la zone du lifespan + include_router :

```bash
cd backend && uv run python -c "import re; src = open('src/agflow/main.py').read(); print(src[src.find('lifespan'):][:1500])"
```

- [ ] Modifier `backend/src/agflow/main.py` :
  - Ajouter l'import en tête (à côté des autres `from agflow.services import …`) :
    ```python
    from agflow.services import git_sync_scheduler
    ```
  - Ajouter dans le lifespan, **après** `await backup_scheduler.start()` :
    ```python
    await git_sync_scheduler.start()
    ```
  - Ajouter **avant** `await backup_scheduler.stop()` dans le bloc d'arrêt :
    ```python
    await git_sync_scheduler.stop()
    ```
  - Ajouter à côté des autres `app.include_router(...)` :
    ```python
    from agflow.api.admin import git_sync as git_sync_router
    app.include_router(git_sync_router.router)
    ```

### Step 5 — Lancer les tests (passing)

- [ ] Lancer : `cd backend && uv run pytest tests/api/test_admin_git_sync.py -v`
- [ ] Attendu : 12 tests PASSED.

### Step 6 — Lint + tsc-equivalent (mypy si configuré, sinon skip)

- [ ] Lancer : `cd backend && uv run ruff check src/agflow/api/admin/git_sync.py src/agflow/main.py tests/api/test_admin_git_sync.py`

### Step 7 — Commit

- [ ] Lancer :

```bash
git add backend/src/agflow/api/admin/git_sync.py backend/src/agflow/main.py backend/tests/api/test_admin_git_sync.py
git commit -m "feat(git-sync-api): 9 endpoints REST + branchement main.py (lifespan + router)"
```

---

## Tâche 7 — Frontend : gitSyncApi.ts + useGitSync.ts

**Files:**
- Create: `frontend/src/lib/gitSyncApi.ts`
- Create: `frontend/src/hooks/useGitSync.ts`
- Test: `frontend/src/lib/__tests__/gitSyncApi.test.ts`
- Test: `frontend/src/hooks/__tests__/useGitSync.test.ts`

### Step 1 — Écrire le test du parser (failing)

- [ ] Créer `frontend/src/lib/__tests__/gitSyncApi.test.ts` :

```ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import * as api from "../gitSyncApi";

const fetchMock = vi.fn();
beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

describe("gitSyncApi.fetchConfig", () => {
  it("returns null on 404", async () => {
    fetchMock.mockResolvedValue({ ok: false, status: 404 });
    const result = await api.fetchConfig();
    expect(result).toBeNull();
  });

  it("returns parsed config on 200", async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        repo_url: "https://github.com/owner/repo",
        auth_mode: "pat_https",
        auth_secret_ref: "${vault://default:git/pat}",
        branch: "main",
        commit_author_name: "bot",
        commit_author_email: "bot@local",
        excluded_columns: {},
        selected_tables: ["users"],
        cron_expr: null,
        cron_enabled: false,
        last_export_at: null,
        last_export_status: null,
        last_export_sha: null,
        last_export_error: null,
        last_export_tables_count: null,
        last_import_at: null,
        last_import_status: null,
        last_import_error: null,
        last_import_rows_inserted: null,
        last_import_rows_updated: null,
        last_import_rows_deleted: null,
        created_at: "2026-05-17T00:00:00Z",
        updated_at: "2026-05-17T00:00:00Z",
      }),
    });
    const result = await api.fetchConfig();
    expect(result?.repo_url).toBe("https://github.com/owner/repo");
  });
});

describe("gitSyncApi.testSecretRef", () => {
  it("posts ref to /test-secret-ref", async () => {
    fetchMock.mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({ ok: true, error: null }),
    });
    const result = await api.testSecretRef("${vault://default:git/pat}");
    expect(result.ok).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/admin/git-sync/test-secret-ref",
      expect.objectContaining({ method: "POST" }),
    );
  });
});
```

### Step 2 — Vérifier l'échec

- [ ] Lancer : `cd frontend && npm test -- src/lib/__tests__/gitSyncApi.test.ts`
- [ ] Attendu : Cannot find module '../gitSyncApi'.

### Step 3 — Écrire le client API

- [ ] Créer `frontend/src/lib/gitSyncApi.ts` :

```ts
export type AuthMode = "ssh_key" | "pat_https" | "basic_https";
export type RunStatus = "ok" | "failed";

export type GitSyncConfig = {
  repo_url: string;
  auth_mode: AuthMode;
  auth_secret_ref: string;
  branch: string;
  commit_author_name: string;
  commit_author_email: string;
  excluded_columns: Record<string, string[]>;
  selected_tables: string[];
  cron_expr: string | null;
  cron_enabled: boolean;
  last_export_at: string | null;
  last_export_status: RunStatus | null;
  last_export_sha: string | null;
  last_export_error: string | null;
  last_export_tables_count: number | null;
  last_import_at: string | null;
  last_import_status: RunStatus | null;
  last_import_error: string | null;
  last_import_rows_inserted: number | null;
  last_import_rows_updated: number | null;
  last_import_rows_deleted: number | null;
  created_at: string;
  updated_at: string;
};

export type GitSyncConfigUpsert = {
  repo_url: string;
  auth_mode: AuthMode;
  auth_secret_ref: string;
  branch: string;
  commit_author_name: string;
  commit_author_email: string;
  excluded_columns: Record<string, string[]>;
  selected_tables: string[];
  cron_expr: string | null;
  cron_enabled: boolean;
};

export type GitSyncTestSecretRefResult = { ok: boolean; error: string | null };
export type GitSyncExportResult = { sha: string; tables_count: number };
export type GitSyncTablePreview = {
  table: string;
  to_insert: number;
  to_update: number;
  to_delete: number;
};
export type GitSyncImportPreview = { tables: GitSyncTablePreview[] };
export type GitSyncImportResult = {
  rows_inserted: number;
  rows_updated: number;
  rows_deleted: number;
};
export type GitSyncCommit = {
  sha: string;
  short_sha: string;
  message: string;
  author_name: string;
  author_email: string;
  authored_at: string;
  html_url: string;
};

const BASE = "/api/admin/git-sync";

async function _json<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`HTTP ${resp.status}: ${text}`);
  }
  return (await resp.json()) as T;
}

export async function fetchConfig(): Promise<GitSyncConfig | null> {
  const resp = await fetch(`${BASE}/config`);
  if (resp.status === 404) return null;
  return _json<GitSyncConfig>(resp);
}

export async function upsertConfig(payload: GitSyncConfigUpsert): Promise<GitSyncConfig> {
  const resp = await fetch(`${BASE}/config`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return _json<GitSyncConfig>(resp);
}

export async function deleteConfig(): Promise<void> {
  const resp = await fetch(`${BASE}/config`, { method: "DELETE" });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
}

export async function listAvailableTables(): Promise<string[]> {
  return _json<string[]>(await fetch(`${BASE}/available-tables`));
}

export async function testSecretRef(authSecretRef: string): Promise<GitSyncTestSecretRefResult> {
  const resp = await fetch(`${BASE}/test-secret-ref`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ auth_secret_ref: authSecretRef }),
  });
  return _json<GitSyncTestSecretRefResult>(resp);
}

export async function runExport(): Promise<GitSyncExportResult> {
  return _json<GitSyncExportResult>(
    await fetch(`${BASE}/export`, { method: "POST" }),
  );
}

export async function previewImport(): Promise<GitSyncImportPreview> {
  return _json<GitSyncImportPreview>(
    await fetch(`${BASE}/preview-import`, { method: "POST" }),
  );
}

export async function runImport(): Promise<GitSyncImportResult> {
  return _json<GitSyncImportResult>(
    await fetch(`${BASE}/import`, { method: "POST" }),
  );
}

export async function listCommits(limit = 30): Promise<GitSyncCommit[]> {
  return _json<GitSyncCommit[]>(
    await fetch(`${BASE}/commits?limit=${limit}`),
  );
}
```

### Step 4 — Lancer le test api (passing)

- [ ] Lancer : `cd frontend && npm test -- src/lib/__tests__/gitSyncApi.test.ts`
- [ ] Attendu : 3 tests PASS.

### Step 5 — Écrire le hook

- [ ] Créer `frontend/src/hooks/useGitSync.ts` :

```ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import * as api from "@/lib/gitSyncApi";

const KEY_CONFIG = ["git-sync", "config"] as const;
const KEY_TABLES = ["git-sync", "available-tables"] as const;
const KEY_COMMITS = (limit: number) => ["git-sync", "commits", limit] as const;

export function useGitSyncConfig() {
  return useQuery({
    queryKey: KEY_CONFIG,
    queryFn: api.fetchConfig,
    refetchInterval: 30_000,
  });
}

export function useAvailableTables() {
  return useQuery({
    queryKey: KEY_TABLES,
    queryFn: api.listAvailableTables,
    staleTime: 5 * 60_000,
  });
}

export function useGitSyncCommits(limit = 30, enabled = true) {
  return useQuery({
    queryKey: KEY_COMMITS(limit),
    queryFn: () => api.listCommits(limit),
    refetchInterval: 60_000,
    enabled,
  });
}

export function useUpsertConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.upsertConfig,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEY_CONFIG });
    },
  });
}

export function useDeleteConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.deleteConfig,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEY_CONFIG });
    },
  });
}

export function useTestSecretRef() {
  return useMutation({ mutationFn: api.testSecretRef });
}

export function useRunExport() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.runExport,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEY_CONFIG });
      qc.invalidateQueries({ queryKey: ["git-sync", "commits"] });
    },
  });
}

export function usePreviewImport() {
  return useMutation({ mutationFn: api.previewImport });
}

export function useRunImport() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: api.runImport,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEY_CONFIG });
    },
  });
}
```

### Step 6 — TSC check

- [ ] Lancer : `cd frontend && npx tsc --noEmit`
- [ ] Attendu : 0 erreur.

### Step 7 — Commit

- [ ] Lancer :

```bash
git add frontend/src/lib/gitSyncApi.ts frontend/src/hooks/useGitSync.ts frontend/src/lib/__tests__/gitSyncApi.test.ts
git commit -m "feat(git-sync-ui): gitSyncApi.ts + useGitSync.ts (TanStack Query hooks)"
```

---

## Tâche 8 — i18n FR/EN + Dialog config + Section config

**Files:**
- Modify: `frontend/src/i18n/fr.json` (+~60 lignes)
- Modify: `frontend/src/i18n/en.json` (+~60 lignes)
- Create: `frontend/src/components/settings/GitSyncConfigDialog.tsx`
- Create: `frontend/src/components/settings/GitSyncConfigSection.tsx`

### Step 1 — Ajouter les clés i18n

- [ ] Ouvrir `frontend/src/i18n/fr.json` et ajouter sous `settings.*` (clé `gitSync`) :

```json
"gitSync": {
  "tabLabel": "Git Sync",
  "empty": {
    "title": "Pas encore configuré",
    "subtitle": "Configurez un dépôt Git distant pour synchroniser la configuration.",
    "cta": "Configurer Git Sync"
  },
  "config": {
    "title": "Configuration",
    "repoUrl": "URL du dépôt",
    "branch": "Branche",
    "authMode": "Mode d'authentification",
    "authMode.ssh_key": "Clé SSH",
    "authMode.pat_https": "Token HTTPS (PAT)",
    "authMode.basic_https": "Basic HTTPS",
    "authSecretRef": "Référence Harpocrate du secret",
    "authSecretRefHint": "Format : ${vault://<coffre>:<chemin>}",
    "testHarpocrate": "Tester la résolution Harpocrate",
    "commitAuthorName": "Auteur (nom)",
    "commitAuthorEmail": "Auteur (email)",
    "selectedTables": "Tables à synchroniser",
    "selectedTablesEmpty": "Aucune table sélectionnée",
    "excludedColumns": "Colonnes exclues (JSON)",
    "excludedColumnsHint": "Format : {\"users\": [\"password_hash\"]}",
    "cron": "Planification",
    "cronEnabled": "Activer la planification automatique",
    "cronExpr": "Expression cron",
    "cronPresets": {
      "hourly": "Toutes les heures",
      "daily4am": "Quotidien à 4h",
      "weeklySun2am": "Hebdomadaire dimanche 2h"
    },
    "save": "Enregistrer",
    "edit": "Modifier",
    "delete": "Supprimer la configuration",
    "deleteConfirm": "Confirmer la suppression de la configuration Git Sync ?"
  },
  "actions": {
    "title": "Actions",
    "exportNow": "Exporter maintenant",
    "previewImport": "Aperçu de l'import",
    "runImport": "Importer depuis Git",
    "importWarning": "Cette action modifie irréversiblement la base. Faites un backup avant."
  },
  "lastExport": {
    "title": "Dernier export",
    "never": "Jamais exécuté",
    "ok": "OK",
    "failed": "Échec",
    "tablesCount_one": "{{count}} table",
    "tablesCount_other": "{{count}} tables"
  },
  "lastImport": {
    "title": "Dernier import",
    "never": "Jamais exécuté",
    "ok": "OK",
    "failed": "Échec",
    "inserted": "Insérées",
    "updated": "Modifiées",
    "deleted": "Supprimées"
  },
  "history": {
    "title": "Historique GitHub",
    "unsupportedHost": "Listing non supporté pour cet hôte. Voir le dépôt : ",
    "empty": "Aucun commit",
    "refresh": "Rafraîchir",
    "openOnGitHub": "Voir sur GitHub"
  },
  "toast": {
    "exportSuccess": "Export réussi : commit {{sha}} ({{count}} tables)",
    "exportFailed": "Échec de l'export : {{error}}",
    "importSuccess": "Import terminé : {{ins}} ajoutées, {{upd}} modifiées, {{del}} supprimées",
    "importFailed": "Échec de l'import : {{error}}",
    "harpocrateOk": "Secret résolu avec succès",
    "harpocrateFailed": "Résolution échouée : {{error}}",
    "configSaved": "Configuration enregistrée",
    "configDeleted": "Configuration supprimée"
  },
  "preview": {
    "title": "Aperçu de l'import",
    "table": "Table",
    "toInsert": "À insérer",
    "toUpdate": "À modifier",
    "toDelete": "À supprimer",
    "empty": "Aucun changement détecté",
    "cancel": "Annuler",
    "confirmImport": "Lancer l'import"
  }
}
```

- [ ] Ouvrir `frontend/src/i18n/en.json` et ajouter la même structure traduite en anglais.

### Step 2 — Créer GitSyncConfigDialog

- [ ] Créer `frontend/src/components/settings/GitSyncConfigDialog.tsx` :

```tsx
import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import { toast } from "sonner";
import {
  useUpsertConfig, useAvailableTables, useTestSecretRef,
} from "@/hooks/useGitSync";
import type { GitSyncConfig, GitSyncConfigUpsert, AuthMode } from "@/lib/gitSyncApi";

const CRON_PRESETS: Record<string, string> = {
  hourly: "0 * * * *",
  daily4am: "0 4 * * *",
  weeklySun2am: "0 2 * * 0",
};

type Props = {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  initial?: GitSyncConfig | null;
};

export function GitSyncConfigDialog({ open, onOpenChange, initial }: Props) {
  const { t } = useTranslation();
  const upsert = useUpsertConfig();
  const test = useTestSecretRef();
  const { data: availableTables } = useAvailableTables();

  const [form, setForm] = useState<GitSyncConfigUpsert>(() => ({
    repo_url: initial?.repo_url ?? "",
    auth_mode: initial?.auth_mode ?? "pat_https",
    auth_secret_ref: initial?.auth_secret_ref ?? "",
    branch: initial?.branch ?? "main",
    commit_author_name: initial?.commit_author_name ?? "agflow bot",
    commit_author_email: initial?.commit_author_email ?? "bot@agflow.local",
    excluded_columns: initial?.excluded_columns ?? {},
    selected_tables: initial?.selected_tables ?? [],
    cron_expr: initial?.cron_expr ?? null,
    cron_enabled: initial?.cron_enabled ?? false,
  }));

  const [excludedJson, setExcludedJson] = useState<string>(
    JSON.stringify(initial?.excluded_columns ?? {}, null, 2),
  );
  const [excludedError, setExcludedError] = useState<string | null>(null);

  useEffect(() => {
    if (open && initial) {
      setForm({
        repo_url: initial.repo_url,
        auth_mode: initial.auth_mode,
        auth_secret_ref: initial.auth_secret_ref,
        branch: initial.branch,
        commit_author_name: initial.commit_author_name,
        commit_author_email: initial.commit_author_email,
        excluded_columns: initial.excluded_columns,
        selected_tables: initial.selected_tables,
        cron_expr: initial.cron_expr,
        cron_enabled: initial.cron_enabled,
      });
      setExcludedJson(JSON.stringify(initial.excluded_columns, null, 2));
    }
  }, [open, initial]);

  const handleTestSecret = async () => {
    if (!form.auth_secret_ref) return;
    const result = await test.mutateAsync(form.auth_secret_ref);
    if (result.ok) toast.success(t("settings.gitSync.toast.harpocrateOk"));
    else toast.error(t("settings.gitSync.toast.harpocrateFailed", { error: result.error }));
  };

  const handleSave = async () => {
    try {
      const parsed = JSON.parse(excludedJson || "{}");
      if (typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new Error("must be an object");
      }
      setExcludedError(null);
      await upsert.mutateAsync({ ...form, excluded_columns: parsed });
      toast.success(t("settings.gitSync.toast.configSaved"));
      onOpenChange(false);
    } catch (e) {
      if (e instanceof SyntaxError || (e as Error).message === "must be an object") {
        setExcludedError(t("settings.gitSync.config.excludedColumnsHint"));
        return;
      }
      toast.error((e as Error).message);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{t("settings.gitSync.config.title")}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4 py-2">
          <div>
            <Label>{t("settings.gitSync.config.repoUrl")}</Label>
            <Input
              value={form.repo_url}
              onChange={(e) => setForm({ ...form, repo_url: e.target.value })}
              placeholder="https://github.com/owner/repo"
            />
          </div>
          <div>
            <Label>{t("settings.gitSync.config.branch")}</Label>
            <Input
              value={form.branch}
              onChange={(e) => setForm({ ...form, branch: e.target.value })}
            />
          </div>
          <div>
            <Label>{t("settings.gitSync.config.authMode")}</Label>
            <Select
              value={form.auth_mode}
              onValueChange={(v) => setForm({ ...form, auth_mode: v as AuthMode })}
            >
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="ssh_key">{t("settings.gitSync.config.authMode.ssh_key")}</SelectItem>
                <SelectItem value="pat_https">{t("settings.gitSync.config.authMode.pat_https")}</SelectItem>
                <SelectItem value="basic_https">{t("settings.gitSync.config.authMode.basic_https")}</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label>{t("settings.gitSync.config.authSecretRef")}</Label>
            <div className="flex gap-2">
              <Input
                value={form.auth_secret_ref}
                onChange={(e) => setForm({ ...form, auth_secret_ref: e.target.value })}
                placeholder="${vault://default:git/pat}"
              />
              <Button variant="outline" onClick={handleTestSecret} disabled={!form.auth_secret_ref || test.isPending}>
                {t("settings.gitSync.config.testHarpocrate")}
              </Button>
            </div>
            <p className="text-xs text-muted-foreground mt-1">{t("settings.gitSync.config.authSecretRefHint")}</p>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <Label>{t("settings.gitSync.config.commitAuthorName")}</Label>
              <Input
                value={form.commit_author_name}
                onChange={(e) => setForm({ ...form, commit_author_name: e.target.value })}
              />
            </div>
            <div>
              <Label>{t("settings.gitSync.config.commitAuthorEmail")}</Label>
              <Input
                value={form.commit_author_email}
                onChange={(e) => setForm({ ...form, commit_author_email: e.target.value })}
              />
            </div>
          </div>
          <div>
            <Label>{t("settings.gitSync.config.selectedTables")}</Label>
            <Select
              onValueChange={(v) => {
                if (!form.selected_tables.includes(v)) {
                  setForm({ ...form, selected_tables: [...form.selected_tables, v] });
                }
              }}
            >
              <SelectTrigger><SelectValue placeholder="+ Ajouter une table" /></SelectTrigger>
              <SelectContent>
                {(availableTables ?? []).map((tbl) => (
                  <SelectItem key={tbl} value={tbl}>{tbl}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <div className="flex flex-wrap gap-1 mt-2">
              {form.selected_tables.map((tbl) => (
                <button
                  key={tbl}
                  type="button"
                  className="px-2 py-1 rounded bg-primary/10 text-xs hover:bg-destructive/20"
                  onClick={() => setForm({ ...form, selected_tables: form.selected_tables.filter((x) => x !== tbl) })}
                >
                  {tbl} ×
                </button>
              ))}
            </div>
          </div>
          <div>
            <Label>{t("settings.gitSync.config.excludedColumns")}</Label>
            <Textarea
              value={excludedJson}
              onChange={(e) => setExcludedJson(e.target.value)}
              rows={4}
              className="font-mono text-xs"
            />
            {excludedError && <p className="text-xs text-destructive mt-1">{excludedError}</p>}
            <p className="text-xs text-muted-foreground mt-1">{t("settings.gitSync.config.excludedColumnsHint")}</p>
          </div>
          <div className="border-t pt-3">
            <div className="flex items-center gap-2">
              <Checkbox
                checked={form.cron_enabled}
                onCheckedChange={(v) => setForm({ ...form, cron_enabled: !!v })}
                id="cron-enabled"
              />
              <Label htmlFor="cron-enabled">{t("settings.gitSync.config.cronEnabled")}</Label>
            </div>
            <Input
              className="mt-2 font-mono"
              value={form.cron_expr ?? ""}
              onChange={(e) => setForm({ ...form, cron_expr: e.target.value || null })}
              placeholder="0 4 * * *"
              disabled={!form.cron_enabled}
            />
            <div className="flex gap-1 mt-1">
              {Object.entries(CRON_PRESETS).map(([key, val]) => (
                <Button
                  key={key}
                  type="button"
                  variant="ghost"
                  size="sm"
                  disabled={!form.cron_enabled}
                  onClick={() => setForm({ ...form, cron_expr: val })}
                >
                  {t(`settings.gitSync.config.cronPresets.${key}`)}
                </Button>
              ))}
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Annuler</Button>
          <Button onClick={handleSave} disabled={upsert.isPending || form.selected_tables.length === 0}>
            {t("settings.gitSync.config.save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
```

### Step 3 — Créer GitSyncConfigSection

- [ ] Créer `frontend/src/components/settings/GitSyncConfigSection.tsx` :

```tsx
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { toast } from "sonner";
import { GitSyncConfigDialog } from "./GitSyncConfigDialog";
import { useDeleteConfig } from "@/hooks/useGitSync";
import type { GitSyncConfig } from "@/lib/gitSyncApi";

type Props = { config: GitSyncConfig };

export function GitSyncConfigSection({ config }: Props) {
  const { t } = useTranslation();
  const [editOpen, setEditOpen] = useState(false);
  const [delOpen, setDelOpen] = useState(false);
  const del = useDeleteConfig();

  const handleDelete = async () => {
    await del.mutateAsync();
    toast.success(t("settings.gitSync.toast.configDeleted"));
    setDelOpen(false);
  };

  return (
    <>
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>{t("settings.gitSync.config.title")}</CardTitle>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => setEditOpen(true)}>
              {t("settings.gitSync.config.edit")}
            </Button>
            <Button variant="outline" size="sm" onClick={() => setDelOpen(true)}>
              {t("settings.gitSync.config.delete")}
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <div>
            <span className="text-muted-foreground">{t("settings.gitSync.config.repoUrl")}: </span>
            <a href={config.repo_url} target="_blank" rel="noreferrer" className="underline">
              {config.repo_url}
            </a>
          </div>
          <div>
            <span className="text-muted-foreground">{t("settings.gitSync.config.branch")}: </span>
            <Badge variant="secondary">{config.branch}</Badge>
          </div>
          <div>
            <span className="text-muted-foreground">{t("settings.gitSync.config.authMode")}: </span>
            <Badge>{config.auth_mode}</Badge>
          </div>
          <div>
            <span className="text-muted-foreground">{t("settings.gitSync.config.selectedTables")}: </span>
            <Badge variant="outline">{config.selected_tables.length}</Badge>
          </div>
          <div>
            <span className="text-muted-foreground">{t("settings.gitSync.config.cron")}: </span>
            {config.cron_enabled && config.cron_expr ? (
              <Badge className="bg-green-600">{config.cron_expr}</Badge>
            ) : (
              <Badge variant="secondary">Désactivé</Badge>
            )}
          </div>
        </CardContent>
      </Card>

      <GitSyncConfigDialog open={editOpen} onOpenChange={setEditOpen} initial={config} />

      <AlertDialog open={delOpen} onOpenChange={setDelOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("settings.gitSync.config.delete")}</AlertDialogTitle>
            <AlertDialogDescription>
              {t("settings.gitSync.config.deleteConfirm")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Annuler</AlertDialogCancel>
            <AlertDialogAction onClick={handleDelete}>OK</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
```

### Step 4 — TSC check

- [ ] Lancer : `cd frontend && npx tsc --noEmit`
- [ ] Attendu : 0 erreur.

### Step 5 — Commit

- [ ] Lancer :

```bash
git add frontend/src/i18n/fr.json frontend/src/i18n/en.json frontend/src/components/settings/GitSyncConfigDialog.tsx frontend/src/components/settings/GitSyncConfigSection.tsx
git commit -m "feat(git-sync-ui): i18n FR/EN + ConfigDialog + ConfigSection"
```

---

## Tâche 9 — Sections Actions + History + Preview Dialog

**Files:**
- Create: `frontend/src/components/settings/GitSyncPreviewDialog.tsx`
- Create: `frontend/src/components/settings/GitSyncActionsSection.tsx`
- Create: `frontend/src/components/settings/GitSyncHistorySection.tsx`

### Step 1 — Créer GitSyncPreviewDialog

- [ ] Créer `frontend/src/components/settings/GitSyncPreviewDialog.tsx` :

```tsx
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { toast } from "sonner";
import { usePreviewImport, useRunImport } from "@/hooks/useGitSync";
import type { GitSyncImportPreview } from "@/lib/gitSyncApi";

type Props = {
  open: boolean;
  onOpenChange: (v: boolean) => void;
};

export function GitSyncPreviewDialog({ open, onOpenChange }: Props) {
  const { t } = useTranslation();
  const preview = usePreviewImport();
  const runImport = useRunImport();
  const [data, setData] = useState<GitSyncImportPreview | null>(null);

  useEffect(() => {
    if (open) {
      setData(null);
      preview.mutateAsync().then(setData).catch((e) => {
        toast.error((e as Error).message);
        onOpenChange(false);
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const handleConfirm = async () => {
    try {
      const r = await runImport.mutateAsync();
      toast.success(t("settings.gitSync.toast.importSuccess", {
        ins: r.rows_inserted, upd: r.rows_updated, del: r.rows_deleted,
      }));
      onOpenChange(false);
    } catch (e) {
      toast.error(t("settings.gitSync.toast.importFailed", { error: (e as Error).message }));
    }
  };

  const totals = data?.tables.reduce(
    (acc, t) => ({
      ins: acc.ins + t.to_insert,
      upd: acc.upd + t.to_update,
      del: acc.del + t.to_delete,
    }),
    { ins: 0, upd: 0, del: 0 },
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>{t("settings.gitSync.preview.title")}</DialogTitle>
        </DialogHeader>
        {preview.isPending && <p>…</p>}
        {data && data.tables.length === 0 && <p>{t("settings.gitSync.preview.empty")}</p>}
        {data && data.tables.length > 0 && (
          <>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t("settings.gitSync.preview.table")}</TableHead>
                  <TableHead className="text-right">{t("settings.gitSync.preview.toInsert")}</TableHead>
                  <TableHead className="text-right">{t("settings.gitSync.preview.toUpdate")}</TableHead>
                  <TableHead className="text-right">{t("settings.gitSync.preview.toDelete")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.tables.map((row) => (
                  <TableRow key={row.table}>
                    <TableCell className="font-mono text-xs">{row.table}</TableCell>
                    <TableCell className="text-right">{row.to_insert}</TableCell>
                    <TableCell className="text-right">{row.to_update}</TableCell>
                    <TableCell className="text-right">{row.to_delete}</TableCell>
                  </TableRow>
                ))}
                {totals && (
                  <TableRow className="font-semibold border-t-2">
                    <TableCell>Total</TableCell>
                    <TableCell className="text-right">{totals.ins}</TableCell>
                    <TableCell className="text-right">{totals.upd}</TableCell>
                    <TableCell className="text-right">{totals.del}</TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
            <p className="text-sm text-destructive">{t("settings.gitSync.actions.importWarning")}</p>
          </>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("settings.gitSync.preview.cancel")}
          </Button>
          <Button
            variant="destructive"
            onClick={handleConfirm}
            disabled={!data || data.tables.length === 0 || runImport.isPending}
          >
            {t("settings.gitSync.preview.confirmImport")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
```

### Step 2 — Créer GitSyncActionsSection

- [ ] Créer `frontend/src/components/settings/GitSyncActionsSection.tsx` :

```tsx
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import { useRunExport } from "@/hooks/useGitSync";
import { GitSyncPreviewDialog } from "./GitSyncPreviewDialog";
import type { GitSyncConfig } from "@/lib/gitSyncApi";

type Props = { config: GitSyncConfig };

function fmtDate(iso: string | null): string {
  return iso ? new Date(iso).toLocaleString() : "—";
}

export function GitSyncActionsSection({ config }: Props) {
  const { t } = useTranslation();
  const exp = useRunExport();
  const [previewOpen, setPreviewOpen] = useState(false);

  const handleExport = async () => {
    try {
      const r = await exp.mutateAsync();
      toast.success(t("settings.gitSync.toast.exportSuccess", {
        sha: r.sha.slice(0, 7), count: r.tables_count,
      }));
    } catch (e) {
      toast.error(t("settings.gitSync.toast.exportFailed", { error: (e as Error).message }));
    }
  };

  return (
    <>
      <Card>
        <CardHeader><CardTitle>{t("settings.gitSync.actions.title")}</CardTitle></CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          <Button onClick={handleExport} disabled={exp.isPending}>
            {t("settings.gitSync.actions.exportNow")}
          </Button>
          <Button variant="outline" onClick={() => setPreviewOpen(true)}>
            {t("settings.gitSync.actions.previewImport")}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>{t("settings.gitSync.lastExport.title")}</CardTitle></CardHeader>
        <CardContent className="space-y-1 text-sm">
          {config.last_export_at === null ? (
            <p className="text-muted-foreground">{t("settings.gitSync.lastExport.never")}</p>
          ) : (
            <>
              <div>
                <Badge className={config.last_export_status === "ok" ? "bg-green-600" : "bg-destructive"}>
                  {t(`settings.gitSync.lastExport.${config.last_export_status}`)}
                </Badge>
                <span className="ml-2 text-muted-foreground">{fmtDate(config.last_export_at)}</span>
              </div>
              {config.last_export_sha && (
                <div>
                  <span className="text-muted-foreground">SHA: </span>
                  <code className="text-xs">{config.last_export_sha.slice(0, 7)}</code>
                </div>
              )}
              {config.last_export_tables_count !== null && (
                <div>{t("settings.gitSync.lastExport.tablesCount", { count: config.last_export_tables_count })}</div>
              )}
              {config.last_export_error && (
                <p className="text-xs text-destructive font-mono">{config.last_export_error}</p>
              )}
            </>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader><CardTitle>{t("settings.gitSync.lastImport.title")}</CardTitle></CardHeader>
        <CardContent className="space-y-1 text-sm">
          {config.last_import_at === null ? (
            <p className="text-muted-foreground">{t("settings.gitSync.lastImport.never")}</p>
          ) : (
            <>
              <div>
                <Badge className={config.last_import_status === "ok" ? "bg-green-600" : "bg-destructive"}>
                  {t(`settings.gitSync.lastImport.${config.last_import_status}`)}
                </Badge>
                <span className="ml-2 text-muted-foreground">{fmtDate(config.last_import_at)}</span>
              </div>
              {config.last_import_status === "ok" && (
                <div className="flex gap-3 text-xs">
                  <span>{t("settings.gitSync.lastImport.inserted")}: {config.last_import_rows_inserted ?? 0}</span>
                  <span>{t("settings.gitSync.lastImport.updated")}: {config.last_import_rows_updated ?? 0}</span>
                  <span>{t("settings.gitSync.lastImport.deleted")}: {config.last_import_rows_deleted ?? 0}</span>
                </div>
              )}
              {config.last_import_error && (
                <p className="text-xs text-destructive font-mono">{config.last_import_error}</p>
              )}
            </>
          )}
        </CardContent>
      </Card>

      <GitSyncPreviewDialog open={previewOpen} onOpenChange={setPreviewOpen} />
    </>
  );
}
```

### Step 3 — Créer GitSyncHistorySection

- [ ] Créer `frontend/src/components/settings/GitSyncHistorySection.tsx` :

```tsx
import { useTranslation } from "react-i18next";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { useGitSyncCommits } from "@/hooks/useGitSync";
import type { GitSyncConfig } from "@/lib/gitSyncApi";

type Props = { config: GitSyncConfig };

function isGithub(url: string): boolean {
  try {
    return new URL(url).hostname === "github.com";
  } catch {
    return false;
  }
}

export function GitSyncHistorySection({ config }: Props) {
  const { t } = useTranslation();
  const isGh = isGithub(config.repo_url);
  const { data: commits, refetch, isFetching } = useGitSyncCommits(30, isGh);

  if (!isGh) {
    return (
      <Card>
        <CardHeader><CardTitle>{t("settings.gitSync.history.title")}</CardTitle></CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            {t("settings.gitSync.history.unsupportedHost")}
            <a href={config.repo_url} target="_blank" rel="noreferrer" className="underline">
              {config.repo_url}
            </a>
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <CardTitle>{t("settings.gitSync.history.title")}</CardTitle>
        <Button variant="outline" size="sm" onClick={() => refetch()} disabled={isFetching}>
          {t("settings.gitSync.history.refresh")}
        </Button>
      </CardHeader>
      <CardContent>
        {commits?.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("settings.gitSync.history.empty")}</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>SHA</TableHead>
                <TableHead>Author</TableHead>
                <TableHead>Message</TableHead>
                <TableHead>Date</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(commits ?? []).map((c) => (
                <TableRow
                  key={c.sha}
                  className="cursor-pointer hover:bg-accent"
                  onClick={() => window.open(c.html_url, "_blank", "noopener,noreferrer")}
                >
                  <TableCell className="font-mono text-xs">{c.short_sha}</TableCell>
                  <TableCell className="text-xs">{c.author_name}</TableCell>
                  <TableCell className="text-xs max-w-md truncate">{c.message.split("\n")[0]}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {new Date(c.authored_at).toLocaleString()}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
```

### Step 4 — TSC check

- [ ] Lancer : `cd frontend && npx tsc --noEmit`
- [ ] Attendu : 0 erreur.

### Step 5 — Commit

- [ ] Lancer :

```bash
git add frontend/src/components/settings/GitSyncPreviewDialog.tsx frontend/src/components/settings/GitSyncActionsSection.tsx frontend/src/components/settings/GitSyncHistorySection.tsx
git commit -m "feat(git-sync-ui): ActionsSection (export+preview+import) + HistorySection (commits GitHub)"
```

---

## Tâche 10 — GitSyncTab + ajout onglet dans SettingsPage

**Files:**
- Create: `frontend/src/components/settings/GitSyncTab.tsx`
- Modify: `frontend/src/pages/SettingsPage.tsx`

### Step 1 — Créer GitSyncTab

- [ ] Créer `frontend/src/components/settings/GitSyncTab.tsx` :

```tsx
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useGitSyncConfig } from "@/hooks/useGitSync";
import { GitSyncConfigDialog } from "./GitSyncConfigDialog";
import { GitSyncConfigSection } from "./GitSyncConfigSection";
import { GitSyncActionsSection } from "./GitSyncActionsSection";
import { GitSyncHistorySection } from "./GitSyncHistorySection";

export function GitSyncTab() {
  const { t } = useTranslation();
  const { data: config, isLoading } = useGitSyncConfig();
  const [createOpen, setCreateOpen] = useState(false);

  if (isLoading) {
    return <p className="text-sm text-muted-foreground">…</p>;
  }

  if (!config) {
    return (
      <>
        <Card>
          <CardContent className="py-8 text-center space-y-3">
            <p className="font-semibold">{t("settings.gitSync.empty.title")}</p>
            <p className="text-sm text-muted-foreground">{t("settings.gitSync.empty.subtitle")}</p>
            <Button onClick={() => setCreateOpen(true)}>{t("settings.gitSync.empty.cta")}</Button>
          </CardContent>
        </Card>
        <GitSyncConfigDialog open={createOpen} onOpenChange={setCreateOpen} initial={null} />
      </>
    );
  }

  return (
    <div className="space-y-4">
      <GitSyncConfigSection config={config} />
      <GitSyncActionsSection config={config} />
      <GitSyncHistorySection config={config} />
    </div>
  );
}
```

### Step 2 — Vérifier la structure actuelle de SettingsPage

- [ ] Lancer : `cd frontend && grep -n "TabsTrigger\|TabsContent" src/pages/SettingsPage.tsx`
- [ ] Identifier la structure des onglets existants (Harpocrate déjà présent).

### Step 3 — Ajouter l'onglet Git Sync dans SettingsPage

- [ ] Modifier `frontend/src/pages/SettingsPage.tsx` :
  - Ajouter en haut : `import { GitSyncTab } from "@/components/settings/GitSyncTab";`
  - Dans `<TabsList>`, ajouter à côté du trigger Harpocrate :
    ```tsx
    <TabsTrigger value="git-sync">{t("settings.gitSync.tabLabel")}</TabsTrigger>
    ```
  - Ajouter à côté du `<TabsContent value="harpocrate">` :
    ```tsx
    <TabsContent value="git-sync"><GitSyncTab /></TabsContent>
    ```

### Step 4 — TSC + lint check

- [ ] Lancer : `cd frontend && npx tsc --noEmit`
- [ ] Attendu : 0 erreur.
- [ ] Lancer : `cd frontend && npm run lint`
- [ ] Attendu : 0 erreur.

### Step 5 — Commit

- [ ] Lancer :

```bash
git add frontend/src/components/settings/GitSyncTab.tsx frontend/src/pages/SettingsPage.tsx
git commit -m "feat(git-sync-ui): GitSyncTab + intégration onglet dans /settings"
```

---

## Tâche 11 — Validation E2E sur LXC fresh

**Files:** Aucun (validation runtime).

### Step 1 — Vérifier le commit history complet

- [ ] Lancer : `git log --oneline dev ^main | head -20`
- [ ] Attendu : ~14 commits préfixés `feat(git-sync-*)`.

### Step 2 — Lancer run-test.sh sur LXC fresh

- [ ] Lancer : `./scripts/run-test.sh`
- [ ] Attendu :
  - LXC fresh créé
  - Code déployé via git pull
  - 8 assertions du smoke kit OK
  - pytest backend complet vert (incluant les ~30 nouveaux tests Git Sync)
  - **Si DB tests échouaient en local (Windows ↔ LXC) → ils doivent passer ici**

### Step 3 — Smoke métier manuel (sur l'instance LXC fresh)

Suivre la procédure du spec §Tests → Validation E2E §Smoke métier post-déploiement (11 étapes). Vérifier en particulier :
- [ ] Configuration sauvegardée et persistée
- [ ] « Tester la résolution Harpocrate » → toast OK
- [ ] Bouton « Exporter maintenant » → commit visible sur GitHub
- [ ] Section « Historique GitHub » : liste affichée, clic ouvre la page commit dans un nouvel onglet
- [ ] Bouton « Aperçu import » sur instance vierge → counts cohérents
- [ ] Bouton « Importer » → rows visibles en DB
- [ ] Activer cron `*/2 * * * *`, attendre 2 min → nouveau commit auto sur GitHub

### Step 4 — Cleanup LXC

- [ ] Lancer : `CLEANUP=1 ./scripts/run-test.sh`
- [ ] Attendu : LXC purgé.

### Step 5 — Tag final

- [ ] (Optionnel selon décision utilisateur) Ne pas tag, simplement reporter à l'utilisateur que tout est validé.

---

## Récapitulatif

**~14 commits livrés :**
1. `feat(git-sync-db): migration 110 git_sync_config (singleton) + schémas Pydantic`
2. `feat(git-sync-service): CRUD config singleton + list_available_tables + record_*_run`
3. `feat(git-sync-service): github_client (parse_repo_url + list_commits)`
4. `feat(git-sync-service): runner (wrappers SDK export/preview/import + test_secret_ref)`
5. `feat(git-sync-scheduler): APScheduler dédié + tick reload 30s + trigger_now`
6. `feat(git-sync-api): 9 endpoints REST + branchement main.py (lifespan + router)`
7. `feat(git-sync-ui): gitSyncApi.ts + useGitSync.ts (TanStack Query hooks)`
8. `feat(git-sync-ui): i18n FR/EN + ConfigDialog + ConfigSection`
9. `feat(git-sync-ui): ActionsSection (export+preview+import) + HistorySection (commits GitHub)`
10. `feat(git-sync-ui): GitSyncTab + intégration onglet dans /settings`

**~38 nouveaux tests** (4 migration + 8 service + 7 github_client + 7 runner + 5 scheduler + 12 api + 3 frontend).

**Wall time estimé :** 2-3 jours en mode pipeline allégé.
