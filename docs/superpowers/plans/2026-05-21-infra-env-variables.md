# Variables d'environnement infra (variante + machine + check projet) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Déclarer les variables d'environnement sur les variantes typées, les remplir sur chaque machine, et vérifier la complétude dans les projets.

**Architecture:** Deux nouvelles tables PostgreSQL (`infra_named_type_env_vars` contract + `infra_machine_env_vars` implémentation) avec FK stricte et CASCADE. Le service `infra_env_vars_service` expose CRUD + upsert atomique + résolution via `platform_secrets_service`. L'UI ajoute une section dans les dialogs existants (variante typée, machine) et une bannière dans ProjectDetailPage.

**Tech Stack:** Python 3.12 + FastAPI + asyncpg + Pydantic v2 ; React 18 + TypeScript strict + TanStack Query + shadcn/ui + i18next ; PostgreSQL 16.

**Spec:** `docs/superpowers/specs/2026-05-21-infra-env-variables-design.md`

---

## Fichiers créés / modifiés

| Action | Chemin |
|--------|--------|
| Créer | `backend/migrations/121_infra_env_variables.sql` |
| Créer | `backend/src/agflow/schemas/infra_env_vars.py` |
| Créer | `backend/src/agflow/services/infra_env_vars_service.py` |
| Créer | `backend/tests/services/test_infra_env_vars_service.py` |
| Modifier | `backend/src/agflow/api/infra/named_types.py` |
| Modifier | `backend/src/agflow/api/infra/machines.py` |
| Modifier | `backend/src/agflow/api/admin/projects.py` |
| Créer | `frontend/src/lib/infraEnvVarsApi.ts` |
| Créer | `frontend/src/hooks/useInfraEnvVars.ts` |
| Créer | `frontend/src/components/NamedTypeEnvVarsSection.tsx` |
| Créer | `frontend/src/components/__tests__/NamedTypeEnvVarsSection.test.tsx` |
| Créer | `frontend/src/components/MachineEnvVarsSection.tsx` |
| Créer | `frontend/src/components/__tests__/MachineEnvVarsSection.test.tsx` |
| Modifier | `frontend/src/pages/InfraNamedTypesPage.tsx` |
| Modifier | `frontend/src/pages/InfraMachinesPage.tsx` |
| Modifier | `frontend/src/pages/ProjectDetailPage.tsx` |
| Modifier | `frontend/src/i18n/fr.json` |
| Modifier | `frontend/src/i18n/en.json` |

---

## Task 1: Migration SQL 121

**Files:**
- Create: `backend/migrations/121_infra_env_variables.sql`

**Contexte:** Les migrations précédentes montrent le pattern : `gen_random_uuid()`, trigger `set_updated_at()`, `CREATE INDEX IF NOT EXISTS`. Voir `119_group_variables.sql` comme référence. Le runner de migrations est dans `backend/src/agflow/db/migrations.py` et applique les fichiers dans l'ordre alphabétique.

- [ ] **Step 1: Écrire la migration**

```sql
-- 121_infra_env_variables.sql
-- Variables d'environnement déclarées par variante typée (infra_named_types)
-- et remplies par chaque machine (infra_machines).
--
-- Flux : variante déclare les noms (contrat) → machine remplit les valeurs.
-- La valeur peut être :
--   - littérale : "my-hostname"
--   - référence vault : "${vault://BACKUPS:PGPASSWORD}"
--   - référence env OS : "${env://HOME}"
-- Résolution faite au runtime par platform_secrets_service.resolve_platform_refs.

CREATE TABLE IF NOT EXISTS infra_named_type_env_vars (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    named_type_id UUID NOT NULL REFERENCES infra_named_types(id) ON DELETE CASCADE,
    name          VARCHAR(128) NOT NULL,
    description   TEXT NOT NULL DEFAULT '',
    position      INT NOT NULL DEFAULT 0,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (named_type_id, name)
);

CREATE INDEX IF NOT EXISTS idx_nt_env_vars_named_type
    ON infra_named_type_env_vars(named_type_id);

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'trg_nt_env_vars_updated_at'
    ) THEN
        CREATE TRIGGER trg_nt_env_vars_updated_at
            BEFORE UPDATE ON infra_named_type_env_vars
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS infra_machine_env_vars (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    machine_id            UUID NOT NULL REFERENCES infra_machines(id) ON DELETE CASCADE,
    named_type_env_var_id UUID NOT NULL REFERENCES infra_named_type_env_vars(id) ON DELETE CASCADE,
    value                 TEXT NOT NULL DEFAULT '',
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (machine_id, named_type_env_var_id)
);

CREATE INDEX IF NOT EXISTS idx_machine_env_vars_machine
    ON infra_machine_env_vars(machine_id);

CREATE INDEX IF NOT EXISTS idx_machine_env_vars_contract
    ON infra_machine_env_vars(named_type_env_var_id);

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'trg_machine_env_vars_updated_at'
    ) THEN
        CREATE TRIGGER trg_machine_env_vars_updated_at
            BEFORE UPDATE ON infra_machine_env_vars
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    END IF;
END $$;
```

- [ ] **Step 2: Appliquer la migration et vérifier**

```bash
cd backend && uv run python -m agflow.db.migrations
```

Expected: `Applied 121_infra_env_variables.sql` dans les logs.

- [ ] **Step 3: Commit**

```bash
git add backend/migrations/121_infra_env_variables.sql
git commit -m "feat(db): migration 121 — infra_named_type_env_vars + infra_machine_env_vars"
```

---

## Task 2: Schémas Pydantic

**Files:**
- Create: `backend/src/agflow/schemas/infra_env_vars.py`

**Contexte:** Voir `backend/src/agflow/schemas/group_variables.py` pour le pattern. Validation du nom via regex en service (pas en schéma) comme dans `group_variables_service.py`, mais ici on la met en schéma via `Field(pattern=...)` pour une validation automatique FastAPI.

- [ ] **Step 1: Écrire le fichier de schemas**

```python
# backend/src/agflow/schemas/infra_env_vars.py
"""Pydantic schemas pour infra_named_type_env_vars + infra_machine_env_vars.

Cf. migration 121 + service infra_env_vars_service.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

_NAME_RE = r"^[A-Za-z_][A-Za-z0-9_]*$"


class NamedTypeEnvVarRow(BaseModel):
    id: UUID
    named_type_id: UUID
    name: str
    description: str = ""
    position: int = 0
    created_at: datetime
    updated_at: datetime


class NamedTypeEnvVarCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128, pattern=_NAME_RE)
    description: str = ""
    position: int = 0


class NamedTypeEnvVarUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128, pattern=_NAME_RE)
    description: str | None = None
    position: int | None = None


class MachineEnvVarRow(BaseModel):
    """Vue dénormalisée : inclut name + description issus du contrat."""
    id: UUID
    machine_id: UUID
    named_type_env_var_id: UUID
    name: str
    description: str
    value: str
    created_at: datetime
    updated_at: datetime


class MachineEnvVarUpsert(BaseModel):
    """Upsert atomique — dict {named_type_env_var_id (str) → value}."""
    values: dict[UUID, str]


class ProjectEnvVarsCheckMissing(BaseModel):
    group_script_id: UUID
    script_id: UUID
    script_name: str
    group_id: UUID
    group_name: str
    machine_id: UUID | None
    machine_name: str | None
    target_kind: str
    missing_env_vars: list[str]


class ProjectEnvVarsCheck(BaseModel):
    project_id: UUID
    total_missing: int
    items: list[ProjectEnvVarsCheckMissing]
```

- [ ] **Step 2: Vérifier le typage strict**

```bash
cd backend && uv run python -c "from agflow.schemas.infra_env_vars import NamedTypeEnvVarRow, MachineEnvVarRow, ProjectEnvVarsCheck; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/src/agflow/schemas/infra_env_vars.py
git commit -m "feat(schemas): infra_env_vars — NamedTypeEnvVar + MachineEnvVar + ProjectEnvVarsCheck"
```

---

## Task 3: Service `infra_env_vars_service`

**Files:**
- Create: `backend/src/agflow/services/infra_env_vars_service.py`

**Contexte:** Suivre exactement le pattern de `group_variables_service.py`. Utiliser `fetch_one`, `fetch_all`, `execute` depuis `agflow.db.pool`. Pour `resolve_for_machine`, utiliser `platform_secrets_service.resolve_platform_refs` comme dans `project_deployments_service.py` (ligne ~241). L'upsert atomique utilise `INSERT ... ON CONFLICT DO UPDATE SET` dans une transaction asyncpg.

- [ ] **Step 1: Écrire le service**

```python
# backend/src/agflow/services/infra_env_vars_service.py
"""Variables d'environnement infra — CRUD contrat (named_type) + implémentation (machine).

Migration 121. Résolution des refs via platform_secrets_service.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.schemas.infra_env_vars import (
    MachineEnvVarRow,
    NamedTypeEnvVarRow,
    ProjectEnvVarsCheck,
    ProjectEnvVarsCheckMissing,
)

_log = structlog.get_logger(__name__)


class EnvVarNotFoundError(Exception):
    pass


class EnvVarDuplicateError(Exception):
    pass


class EnvVarForeignKeyError(ValueError):
    """named_type_env_var_id n'appartient pas à la variante de la machine."""


# ── helpers ─────────────────────────────────────────────────────────────────

def _to_nt_row(row: dict[str, Any]) -> NamedTypeEnvVarRow:
    return NamedTypeEnvVarRow(
        id=row["id"],
        named_type_id=row["named_type_id"],
        name=row["name"],
        description=row.get("description", ""),
        position=row.get("position", 0),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _to_machine_row(row: dict[str, Any]) -> MachineEnvVarRow:
    return MachineEnvVarRow(
        id=row["id"],
        machine_id=row["machine_id"],
        named_type_env_var_id=row["named_type_env_var_id"],
        name=row["name"],
        description=row.get("description", ""),
        value=row.get("value", ""),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


# ── named_type env vars CRUD ─────────────────────────────────────────────────

async def list_by_named_type(named_type_id: UUID) -> list[NamedTypeEnvVarRow]:
    rows = await fetch_all(
        "SELECT id, named_type_id, name, description, position, created_at, updated_at "
        "FROM infra_named_type_env_vars WHERE named_type_id = $1 ORDER BY position, name",
        named_type_id,
    )
    return [_to_nt_row(r) for r in rows]


async def get_env_var_by_id(env_var_id: UUID) -> NamedTypeEnvVarRow:
    row = await fetch_one(
        "SELECT id, named_type_id, name, description, position, created_at, updated_at "
        "FROM infra_named_type_env_vars WHERE id = $1",
        env_var_id,
    )
    if row is None:
        raise EnvVarNotFoundError(f"env_var {env_var_id} not found")
    return _to_nt_row(row)


async def create_env_var(
    named_type_id: UUID,
    name: str,
    description: str = "",
    position: int = 0,
) -> NamedTypeEnvVarRow:
    import asyncpg
    try:
        row = await fetch_one(
            "INSERT INTO infra_named_type_env_vars "
            "  (named_type_id, name, description, position) "
            "VALUES ($1, $2, $3, $4) "
            "RETURNING id, named_type_id, name, description, position, created_at, updated_at",
            named_type_id, name, description, position,
        )
    except asyncpg.UniqueViolationError as exc:
        raise EnvVarDuplicateError(
            f"env_var {name!r} already exists for named_type {named_type_id}"
        ) from exc
    assert row is not None
    _log.info("infra_env_vars.create", named_type_id=str(named_type_id), name=name)
    return _to_nt_row(row)


async def update_env_var(
    env_var_id: UUID,
    *,
    name: str | None = None,
    description: str | None = None,
    position: int | None = None,
) -> NamedTypeEnvVarRow:
    import asyncpg
    current = await get_env_var_by_id(env_var_id)
    next_name = name if name is not None else current.name
    next_description = description if description is not None else current.description
    next_position = position if position is not None else current.position
    try:
        row = await fetch_one(
            "UPDATE infra_named_type_env_vars "
            "SET name = $2, description = $3, position = $4 "
            "WHERE id = $1 "
            "RETURNING id, named_type_id, name, description, position, created_at, updated_at",
            env_var_id, next_name, next_description, next_position,
        )
    except asyncpg.UniqueViolationError as exc:
        raise EnvVarDuplicateError(
            f"another env_var already uses the name {next_name!r}"
        ) from exc
    assert row is not None
    _log.info("infra_env_vars.update", id=str(env_var_id), name=next_name)
    return _to_nt_row(row)


async def delete_env_var(env_var_id: UUID) -> None:
    await get_env_var_by_id(env_var_id)
    result = await execute(
        "DELETE FROM infra_named_type_env_vars WHERE id = $1", env_var_id,
    )
    if result.endswith(" 0"):
        raise EnvVarNotFoundError(f"env_var {env_var_id} not found")
    _log.info("infra_env_vars.delete", id=str(env_var_id))


# ── machine env vars ─────────────────────────────────────────────────────────

async def list_machine_env_vars(machine_id: UUID) -> list[MachineEnvVarRow]:
    """Retourne toutes les env vars du contrat de la machine (valeur vide si non remplie)."""
    rows = await fetch_all(
        """
        SELECT
            coalesce(mv.id, gen_random_uuid()) AS id,
            $1::uuid                           AS machine_id,
            nv.id                              AS named_type_env_var_id,
            nv.name,
            nv.description,
            coalesce(mv.value, '')             AS value,
            coalesce(mv.created_at, now())     AS created_at,
            coalesce(mv.updated_at, now())     AS updated_at
        FROM infra_machines m
        JOIN infra_named_type_env_vars nv ON nv.named_type_id = m.type_id
        LEFT JOIN infra_machine_env_vars mv
               ON mv.machine_id = $1 AND mv.named_type_env_var_id = nv.id
        WHERE m.id = $1
        ORDER BY nv.position, nv.name
        """,
        machine_id,
    )
    return [_to_machine_row(r) for r in rows]


async def upsert_machine_env_vars(
    machine_id: UUID,
    values: dict[UUID, str],
) -> list[MachineEnvVarRow]:
    """Upsert atomique des valeurs. Lève EnvVarForeignKeyError si un ID est inconnu."""
    if not values:
        return await list_machine_env_vars(machine_id)

    # Vérifier que tous les IDs appartiennent au contrat de la machine
    valid_ids = {
        r["id"]
        for r in await fetch_all(
            """
            SELECT nv.id FROM infra_named_type_env_vars nv
            JOIN infra_machines m ON m.type_id = nv.named_type_id
            WHERE m.id = $1
            """,
            machine_id,
        )
    }
    unknown = set(values.keys()) - valid_ids
    if unknown:
        raise EnvVarForeignKeyError(
            f"env_var ids {unknown} do not belong to machine {machine_id}'s named_type"
        )

    from agflow.db.pool import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            for ev_id, val in values.items():
                await conn.execute(
                    """
                    INSERT INTO infra_machine_env_vars
                        (machine_id, named_type_env_var_id, value)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (machine_id, named_type_env_var_id)
                    DO UPDATE SET value = EXCLUDED.value, updated_at = now()
                    """,
                    machine_id, ev_id, val,
                )

    _log.info("infra_env_vars.upsert_machine", machine_id=str(machine_id), count=len(values))
    return await list_machine_env_vars(machine_id)


async def resolve_for_machine(machine_id: UUID) -> dict[str, str]:
    """Retourne {name: valeur_résolue} pour la machine. Exclut les valeurs vides après résolution."""
    from agflow.services import platform_secrets_service
    secrets_map = await platform_secrets_service.resolve_all()
    rows = await list_machine_env_vars(machine_id)
    result: dict[str, str] = {}
    for row in rows:
        resolved = platform_secrets_service.resolve_platform_refs(row.value, secrets_map)
        if resolved:
            result[row.name] = resolved
    return result


# ── project env vars check ────────────────────────────────────────────────────

async def check_project_env_vars(project_id: UUID) -> ProjectEnvVarsCheck:
    """Vérifie que chaque group_script avec des variables via_env a sa machine complète."""
    from agflow.services import groups_service, group_scripts_service, scripts_service

    groups = await groups_service.list_by_project(project_id)
    items: list[ProjectEnvVarsCheckMissing] = []

    for group in groups:
        group_scripts = await group_scripts_service.list_by_group(group.id)
        for gs in group_scripts:
            script = await scripts_service.get_by_id(gs.script_id)
            via_env_vars = [v for v in script.input_variables if v.via_env]
            if not via_env_vars:
                continue

            # Résoudre la machine effective
            # GroupSummary n'a pas machine_id — utiliser resolve_target_machine_id
            machine_id: UUID | None = None
            machine_name: str | None = gs.machine_name or None

            if gs.target_kind == "fixed_machine" and gs.machine_id:
                machine_id = gs.machine_id
            elif gs.target_kind == "deployment_host":
                try:
                    machine_id = await group_scripts_service.resolve_target_machine_id(gs.id)
                except Exception:
                    pass  # groupe sans machine assignée : skip

            env_available: dict[str, str] = {}
            if machine_id:
                env_available = await resolve_for_machine(machine_id)

            missing = [v.name for v in via_env_vars if v.name not in env_available]
            if missing:
                items.append(ProjectEnvVarsCheckMissing(
                    group_script_id=gs.id,
                    script_id=script.id,
                    script_name=script.name,
                    group_id=group.id,
                    group_name=group.name,
                    machine_id=machine_id,
                    machine_name=machine_name,
                    target_kind=gs.target_kind,
                    missing_env_vars=missing,
                ))

    return ProjectEnvVarsCheck(
        project_id=project_id,
        total_missing=sum(len(it.missing_env_vars) for it in items),
        items=items,
    )
```

- [ ] **Step 2: Vérifier l'import**

```bash
cd backend && uv run python -c "from agflow.services import infra_env_vars_service; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/src/agflow/services/infra_env_vars_service.py
git commit -m "feat(service): infra_env_vars_service — CRUD + upsert machine + resolve + check projet"
```

---

## Task 4: Tests service

**Files:**
- Create: `backend/tests/services/test_infra_env_vars_service.py`

**Contexte:** Pattern identique à `test_backup_schedules_service.py`. La fixture `fresh_db` applique les migrations sur la DB réelle (192.168.10.154). Il faut créer une `infra_named_types` de fixture en insérant directement via SQL — regarder comment `type_id` est structuré (c'est un varchar qui pointe vers une catégorie, pas une FK). Voir `infra_named_types_service` pour le schéma.

**Note préalable :** `infra_named_types.type_id` est un `VARCHAR` référençant `infra_categories.name` (pas une FK). Pour les tests, insérer une catégorie + un named_type de test.

- [ ] **Step 1: Écrire les tests**

```python
# backend/tests/services/test_infra_env_vars_service.py
"""Tests d'intégration pour infra_env_vars_service (DB réelle)."""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest

from agflow.db.pool import execute, fetch_one
from agflow.services import infra_env_vars_service as svc
from agflow.services.infra_env_vars_service import (
    EnvVarDuplicateError,
    EnvVarForeignKeyError,
    EnvVarNotFoundError,
)
from tests._db_reset import reset_schema_and_migrate

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def fresh_db() -> AsyncIterator[None]:
    await reset_schema_and_migrate()
    yield


async def _create_named_type() -> uuid.UUID:
    """Insère une catégorie + un named_type de test, retourne l'id du named_type."""
    # infra_categories(name PRIMARY KEY, is_vps boolean)
    await execute(
        "INSERT INTO infra_categories (name) VALUES ('test-cat') "
        "ON CONFLICT (name) DO NOTHING",
    )
    # infra_named_types.type_id = infra_categories.name (varchar FK)
    nt_id = uuid.uuid4()
    await execute(
        "INSERT INTO infra_named_types (id, name, type_id, connection_type) "
        "VALUES ($1, 'Test NT', 'test-cat', 'SSH')",
        nt_id,
    )
    return nt_id


async def _create_machine(named_type_id: uuid.UUID) -> uuid.UUID:
    """Insère une machine de test liée au named_type.
    infra_machines.type_id = infra_named_types.id (UUID FK).
    """
    m_id = uuid.uuid4()
    await execute(
        "INSERT INTO infra_machines (id, name, type_id, host, port) "
        "VALUES ($1, 'test-machine', $2, '127.0.0.1', 22)",
        m_id, named_type_id,
    )
    return m_id


# ── CRUD named_type env vars ────────────────────────────────────────────────

async def test_create_and_list(fresh_db: None) -> None:
    nt_id = await _create_named_type()
    ev = await svc.create_env_var(nt_id, name="MY_VAR", description="desc", position=1)
    assert ev.name == "MY_VAR"
    assert ev.named_type_id == nt_id
    rows = await svc.list_by_named_type(nt_id)
    assert len(rows) == 1
    assert rows[0].id == ev.id


async def test_get_by_id(fresh_db: None) -> None:
    nt_id = await _create_named_type()
    ev = await svc.create_env_var(nt_id, name="VAR_A")
    fetched = await svc.get_env_var_by_id(ev.id)
    assert fetched.id == ev.id


async def test_get_by_id_not_found(fresh_db: None) -> None:
    with pytest.raises(EnvVarNotFoundError):
        await svc.get_env_var_by_id(uuid.uuid4())


async def test_update_env_var(fresh_db: None) -> None:
    nt_id = await _create_named_type()
    ev = await svc.create_env_var(nt_id, name="OLD_NAME")
    updated = await svc.update_env_var(ev.id, name="NEW_NAME", description="updated")
    assert updated.name == "NEW_NAME"
    assert updated.description == "updated"


async def test_unique_constraint(fresh_db: None) -> None:
    nt_id = await _create_named_type()
    await svc.create_env_var(nt_id, name="SAME")
    with pytest.raises(EnvVarDuplicateError):
        await svc.create_env_var(nt_id, name="SAME")


async def test_delete_env_var(fresh_db: None) -> None:
    nt_id = await _create_named_type()
    ev = await svc.create_env_var(nt_id, name="TO_DELETE")
    await svc.delete_env_var(ev.id)
    with pytest.raises(EnvVarNotFoundError):
        await svc.get_env_var_by_id(ev.id)


async def test_cascade_delete_named_type(fresh_db: None) -> None:
    """Supprimer le named_type supprime ses env vars en cascade."""
    nt_id = await _create_named_type()
    await svc.create_env_var(nt_id, name="CASCADE_VAR")
    await execute("DELETE FROM infra_named_types WHERE id = $1", nt_id)
    rows = await svc.list_by_named_type(nt_id)
    assert rows == []


# ── machine env vars ────────────────────────────────────────────────────────

async def test_list_machine_env_vars_empty(fresh_db: None) -> None:
    """GET retourne les vars du contrat avec value='' si non remplies."""
    nt_id = await _create_named_type()
    m_id = await _create_machine(nt_id)
    await svc.create_env_var(nt_id, name="EMPTY_VAR")
    rows = await svc.list_machine_env_vars(m_id)
    assert len(rows) == 1
    assert rows[0].name == "EMPTY_VAR"
    assert rows[0].value == ""


async def test_upsert_machine_env_vars(fresh_db: None) -> None:
    nt_id = await _create_named_type()
    m_id = await _create_machine(nt_id)
    ev = await svc.create_env_var(nt_id, name="MY_VAR")
    result = await svc.upsert_machine_env_vars(m_id, {ev.id: "hello"})
    assert len(result) == 1
    assert result[0].value == "hello"


async def test_upsert_idempotent(fresh_db: None) -> None:
    nt_id = await _create_named_type()
    m_id = await _create_machine(nt_id)
    ev = await svc.create_env_var(nt_id, name="MY_VAR")
    await svc.upsert_machine_env_vars(m_id, {ev.id: "first"})
    result = await svc.upsert_machine_env_vars(m_id, {ev.id: "second"})
    assert result[0].value == "second"
    # Vérifier qu'il n'y a pas de doublon
    rows_in_db = await fetch_one(
        "SELECT count(*) AS c FROM infra_machine_env_vars WHERE machine_id = $1", m_id,
    )
    assert rows_in_db is not None and rows_in_db["c"] == 1


async def test_upsert_invalid_id(fresh_db: None) -> None:
    nt_id = await _create_named_type()
    m_id = await _create_machine(nt_id)
    with pytest.raises(EnvVarForeignKeyError):
        await svc.upsert_machine_env_vars(m_id, {uuid.uuid4(): "val"})


async def test_cascade_delete_machine(fresh_db: None) -> None:
    nt_id = await _create_named_type()
    m_id = await _create_machine(nt_id)
    ev = await svc.create_env_var(nt_id, name="VAR")
    await svc.upsert_machine_env_vars(m_id, {ev.id: "val"})
    await execute("DELETE FROM infra_machines WHERE id = $1", m_id)
    row = await fetch_one(
        "SELECT count(*) AS c FROM infra_machine_env_vars WHERE machine_id = $1", m_id,
    )
    assert row is not None and row["c"] == 0


async def test_resolve_for_machine_literal(fresh_db: None) -> None:
    nt_id = await _create_named_type()
    m_id = await _create_machine(nt_id)
    ev = await svc.create_env_var(nt_id, name="HOST")
    await svc.upsert_machine_env_vars(m_id, {ev.id: "example.com"})
    resolved = await svc.resolve_for_machine(m_id)
    assert resolved == {"HOST": "example.com"}


async def test_resolve_for_machine_excludes_empty(fresh_db: None) -> None:
    nt_id = await _create_named_type()
    m_id = await _create_machine(nt_id)
    await svc.create_env_var(nt_id, name="EMPTY_HOST")
    resolved = await svc.resolve_for_machine(m_id)
    assert "EMPTY_HOST" not in resolved
```

- [ ] **Step 2: Lancer les tests (tous doivent passer)**

```bash
cd backend && uv run pytest tests/services/test_infra_env_vars_service.py -v
```

Expected: tous les tests PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/services/test_infra_env_vars_service.py
git commit -m "test(service): infra_env_vars_service — CRUD, upsert, cascade, resolve"
```

---

## Task 5: API — endpoints named_types + machines

**Files:**
- Modify: `backend/src/agflow/api/infra/named_types.py`
- Modify: `backend/src/agflow/api/infra/machines.py`

**Contexte:** Les routers existent déjà. Il suffit d'ajouter des endpoints supplémentaires en bas de chaque fichier. Pattern exact : voir `group_variables.py` pour la gestion des erreurs (UniqueViolation → 409, NotFound → 404, ForeignKey → 422).

- [ ] **Step 1: Modifier `named_types.py` — ajouter 4 endpoints**

Ajouter à la fin de `backend/src/agflow/api/infra/named_types.py` :

```python
from agflow.schemas.infra_env_vars import (
    NamedTypeEnvVarCreate,
    NamedTypeEnvVarRow,
    NamedTypeEnvVarUpdate,
)
from agflow.services import infra_env_vars_service


# ── Env vars du contrat (variante typée) ──────────────────────────────────

@router.get("/{named_type_id}/env-vars", response_model=list[NamedTypeEnvVarRow], dependencies=_admin)
async def list_named_type_env_vars(named_type_id: UUID):
    return await infra_env_vars_service.list_by_named_type(named_type_id)


@router.post(
    "/{named_type_id}/env-vars",
    response_model=NamedTypeEnvVarRow,
    status_code=status.HTTP_201_CREATED,
    dependencies=_admin,
)
async def create_named_type_env_var(named_type_id: UUID, payload: NamedTypeEnvVarCreate):
    try:
        return await infra_env_vars_service.create_env_var(
            named_type_id,
            name=payload.name,
            description=payload.description,
            position=payload.position,
        )
    except infra_env_vars_service.EnvVarDuplicateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.put(
    "/{named_type_id}/env-vars/{env_var_id}",
    response_model=NamedTypeEnvVarRow,
    dependencies=_admin,
)
async def update_named_type_env_var(named_type_id: UUID, env_var_id: UUID, payload: NamedTypeEnvVarUpdate):
    try:
        return await infra_env_vars_service.update_env_var(
            env_var_id, **payload.model_dump(exclude_unset=True),
        )
    except infra_env_vars_service.EnvVarNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except infra_env_vars_service.EnvVarDuplicateError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.delete(
    "/{named_type_id}/env-vars/{env_var_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=_admin,
)
async def delete_named_type_env_var(named_type_id: UUID, env_var_id: UUID):
    try:
        await infra_env_vars_service.delete_env_var(env_var_id)
    except infra_env_vars_service.EnvVarNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
```

- [ ] **Step 2: Modifier `machines.py` — ajouter 2 endpoints**

Ajouter à la fin de `backend/src/agflow/api/infra/machines.py` (après les imports existants, ajouter les imports manquants en haut) :

```python
# En haut du fichier, ajouter ces imports aux imports existants :
from agflow.schemas.infra_env_vars import MachineEnvVarRow, MachineEnvVarUpsert
from agflow.services import infra_env_vars_service

# À la fin du fichier, ajouter ces 2 endpoints :

# ── Env vars de la machine ────────────────────────────────────────────────

@router.get("/{machine_id}/env-vars", response_model=list[MachineEnvVarRow], dependencies=_admin)
async def list_machine_env_vars(machine_id: UUID):
    return await infra_env_vars_service.list_machine_env_vars(machine_id)


@router.put("/{machine_id}/env-vars", response_model=list[MachineEnvVarRow], dependencies=_admin)
async def upsert_machine_env_vars(machine_id: UUID, payload: MachineEnvVarUpsert):
    try:
        return await infra_env_vars_service.upsert_machine_env_vars(machine_id, payload.values)
    except infra_env_vars_service.EnvVarForeignKeyError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
```

- [ ] **Step 3: Vérifier que l'app démarre sans erreur**

```bash
cd backend && uv run python -c "from agflow.api.infra.named_types import router; from agflow.api.infra.machines import router; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/src/agflow/api/infra/named_types.py backend/src/agflow/api/infra/machines.py
git commit -m "feat(api): endpoints env-vars — named_types (4) + machines (2)"
```

---

## Task 6: Check projet — endpoint `/env-vars-check`

**Files:**
- Modify: `backend/src/agflow/api/admin/projects.py`

**Contexte:** La fonction `check_project_env_vars` est déjà dans `infra_env_vars_service` (Task 3). Il faut l'exposer en GET dans le router admin/projects.py. Attention : `groups_service.list_by_project` retourne des `GroupSummary` qui ont `machine_id` directement. Vérifier dans `groups_service` si `group.machine_id` existe bien.

- [ ] **Step 1: Vérifier les attributs de GroupSummary**

```bash
cd backend && uv run python -c "from agflow.schemas.products import GroupSummary; print([f.name for f in GroupSummary.model_fields.values()])"
```

Expected: liste incluant `machine_id` et `name`.

- [ ] **Step 2: Ajouter les imports et l'endpoint dans `projects.py`**

Ajouter en haut du fichier, après les imports existants :
```python
from agflow.schemas.infra_env_vars import ProjectEnvVarsCheck
from agflow.services import infra_env_vars_service
```

Ajouter à la fin du fichier :
```python
@router.get("/{project_id}/env-vars-check", response_model=ProjectEnvVarsCheck)
async def check_env_vars(project_id: UUID):
    try:
        await projects_service.get_by_id(project_id)
    except projects_service.ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return await infra_env_vars_service.check_project_env_vars(project_id)
```

- [ ] **Step 3: Vérifier**

```bash
cd backend && uv run python -c "from agflow.api.admin.projects import router; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/src/agflow/api/admin/projects.py
git commit -m "feat(api): GET /admin/projects/{id}/env-vars-check"
```

---

## Task 7: Client TypeScript + hooks

**Files:**
- Create: `frontend/src/lib/infraEnvVarsApi.ts`
- Create: `frontend/src/hooks/useInfraEnvVars.ts`

**Contexte:** Voir `frontend/src/lib/groupVariablesApi.ts` pour le pattern. L'`api` client est dans `frontend/src/lib/api.ts`. Le `useQueryClient` et les hooks React Query suivent le pattern de `useInfra.ts`.

- [ ] **Step 1: Créer `infraEnvVarsApi.ts`**

```typescript
// frontend/src/lib/infraEnvVarsApi.ts
import { api } from "./api";

export interface NamedTypeEnvVar {
  id: string;
  named_type_id: string;
  name: string;
  description: string;
  position: number;
  created_at: string;
  updated_at: string;
}

export interface NamedTypeEnvVarCreate {
  name: string;
  description?: string;
  position?: number;
}

export interface NamedTypeEnvVarUpdate {
  name?: string;
  description?: string;
  position?: number;
}

export interface MachineEnvVar {
  id: string;
  machine_id: string;
  named_type_env_var_id: string;
  name: string;
  description: string;
  value: string;
  created_at: string;
  updated_at: string;
}

export interface MachineEnvVarUpsert {
  values: Record<string, string>;
}

export interface ProjectEnvVarsCheckMissing {
  group_script_id: string;
  script_id: string;
  script_name: string;
  group_id: string;
  group_name: string;
  machine_id: string | null;
  machine_name: string | null;
  target_kind: string;
  missing_env_vars: string[];
}

export interface ProjectEnvVarsCheck {
  project_id: string;
  total_missing: number;
  items: ProjectEnvVarsCheckMissing[];
}

export const namedTypeEnvVarsApi = {
  async list(namedTypeId: string): Promise<NamedTypeEnvVar[]> {
    return (await api.get<NamedTypeEnvVar[]>(`/infra/named-types/${namedTypeId}/env-vars`)).data;
  },
  async create(namedTypeId: string, payload: NamedTypeEnvVarCreate): Promise<NamedTypeEnvVar> {
    return (await api.post<NamedTypeEnvVar>(`/infra/named-types/${namedTypeId}/env-vars`, payload)).data;
  },
  async update(namedTypeId: string, envVarId: string, payload: NamedTypeEnvVarUpdate): Promise<NamedTypeEnvVar> {
    return (await api.put<NamedTypeEnvVar>(`/infra/named-types/${namedTypeId}/env-vars/${envVarId}`, payload)).data;
  },
  async remove(namedTypeId: string, envVarId: string): Promise<void> {
    await api.delete(`/infra/named-types/${namedTypeId}/env-vars/${envVarId}`);
  },
};

export const machineEnvVarsApi = {
  async list(machineId: string): Promise<MachineEnvVar[]> {
    return (await api.get<MachineEnvVar[]>(`/infra/machines/${machineId}/env-vars`)).data;
  },
  async upsert(machineId: string, payload: MachineEnvVarUpsert): Promise<MachineEnvVar[]> {
    return (await api.put<MachineEnvVar[]>(`/infra/machines/${machineId}/env-vars`, payload)).data;
  },
};

export const projectEnvVarsApi = {
  async check(projectId: string): Promise<ProjectEnvVarsCheck> {
    return (await api.get<ProjectEnvVarsCheck>(`/admin/projects/${projectId}/env-vars-check`)).data;
  },
};
```

- [ ] **Step 2: Créer `useInfraEnvVars.ts`**

```typescript
// frontend/src/hooks/useInfraEnvVars.ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  machineEnvVarsApi,
  namedTypeEnvVarsApi,
  projectEnvVarsApi,
  type MachineEnvVarUpsert,
  type NamedTypeEnvVarCreate,
  type NamedTypeEnvVarUpdate,
} from "@/lib/infraEnvVarsApi";

export function useNamedTypeEnvVars(namedTypeId: string | null | undefined) {
  return useQuery({
    queryKey: ["infra-nt-env-vars", namedTypeId ?? ""],
    queryFn: () => namedTypeEnvVarsApi.list(namedTypeId as string),
    enabled: !!namedTypeId,
  });
}

export function useNamedTypeEnvVarsMutations(namedTypeId: string) {
  const qc = useQueryClient();
  const invalidate = () => qc.invalidateQueries({ queryKey: ["infra-nt-env-vars", namedTypeId] });

  const create = useMutation({
    mutationFn: (p: NamedTypeEnvVarCreate) => namedTypeEnvVarsApi.create(namedTypeId, p),
    onSuccess: invalidate,
  });
  const update = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: NamedTypeEnvVarUpdate }) =>
      namedTypeEnvVarsApi.update(namedTypeId, id, payload),
    onSuccess: invalidate,
  });
  const remove = useMutation({
    mutationFn: (id: string) => namedTypeEnvVarsApi.remove(namedTypeId, id),
    onSuccess: invalidate,
  });

  return { create, update, remove };
}

export function useMachineEnvVars(machineId: string | null | undefined) {
  return useQuery({
    queryKey: ["infra-machine-env-vars", machineId ?? ""],
    queryFn: () => machineEnvVarsApi.list(machineId as string),
    enabled: !!machineId,
  });
}

export function useMachineEnvVarsUpsert(machineId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: MachineEnvVarUpsert) => machineEnvVarsApi.upsert(machineId, payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["infra-machine-env-vars", machineId] }),
  });
}

export function useProjectEnvVarsCheck(projectId: string | null | undefined) {
  return useQuery({
    queryKey: ["project-env-vars-check", projectId ?? ""],
    queryFn: () => projectEnvVarsApi.check(projectId as string),
    enabled: !!projectId,
  });
}
```

- [ ] **Step 3: Vérifier la compilation TypeScript**

```bash
cd frontend && npx tsc --noEmit
```

Expected: aucune erreur.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/infraEnvVarsApi.ts frontend/src/hooks/useInfraEnvVars.ts
git commit -m "feat(frontend): infraEnvVarsApi + useInfraEnvVars hooks"
```

---

## Task 8: Composant `NamedTypeEnvVarsSection` + tests

**Files:**
- Create: `frontend/src/components/NamedTypeEnvVarsSection.tsx`
- Create: `frontend/src/components/__tests__/NamedTypeEnvVarsSection.test.tsx`

**Contexte:** Pattern UI : une liste de variables avec colonnes (nom / description / position / actions), un bouton "Ajouter" qui affiche une ligne en édition inline, et un ConfirmDialog (jamais window.confirm) pour la suppression. Voir `GroupVariablesSection.tsx` dans `frontend/src/components/projects/` pour le pattern exact.

- [ ] **Step 1: Créer `NamedTypeEnvVarsSection.tsx`**

```tsx
// frontend/src/components/NamedTypeEnvVarsSection.tsx
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Plus, Trash2, X, Check } from "lucide-react";
import { toast } from "sonner";
import { useNamedTypeEnvVars, useNamedTypeEnvVarsMutations } from "@/hooks/useInfraEnvVars";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const NAME_RE = /^[A-Za-z_][A-Za-z0-9_]*$/;

interface NewRow {
  name: string;
  description: string;
  position: number;
}

export function NamedTypeEnvVarsSection({ namedTypeId }: { namedTypeId: string }) {
  const { t } = useTranslation();
  const { data: envVars = [], isLoading } = useNamedTypeEnvVars(namedTypeId);
  const { create, remove } = useNamedTypeEnvVarsMutations(namedTypeId);
  const [newRow, setNewRow] = useState<NewRow | null>(null);
  const [deleteTargetId, setDeleteTargetId] = useState<string | null>(null);

  async function handleAdd() {
    if (!newRow) return;
    if (!NAME_RE.test(newRow.name)) {
      toast.error(t("infra.env_var_invalid_name"));
      return;
    }
    try {
      await create.mutateAsync({
        name: newRow.name,
        description: newRow.description,
        position: newRow.position,
      });
      setNewRow(null);
      toast.success(t("infra.env_var_added"));
    } catch {
      toast.error(t("infra.env_var_add_error"));
    }
  }

  const deleteTarget = envVars.find((v) => v.id === deleteTargetId);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium">{t("infra.env_vars_title")}</p>
        <Button
          size="sm"
          variant="outline"
          onClick={() => setNewRow({ name: "", description: "", position: envVars.length })}
        >
          <Plus className="w-3.5 h-3.5 mr-1" />
          {t("infra.env_var_add_button")}
        </Button>
      </div>

      {isLoading ? (
        <p className="text-xs text-muted-foreground">…</p>
      ) : envVars.length === 0 && !newRow ? (
        <p className="text-xs text-muted-foreground italic">{t("infra.env_vars_empty")}</p>
      ) : (
        <div className="rounded-md border overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-muted/50">
              <tr>
                <th className="text-left px-3 py-2 font-medium text-xs">{t("infra.env_var_col_name")}</th>
                <th className="text-left px-3 py-2 font-medium text-xs">{t("infra.env_var_col_description")}</th>
                <th className="text-left px-3 py-2 font-medium text-xs w-16">{t("infra.env_var_col_position")}</th>
                <th className="w-8" />
              </tr>
            </thead>
            <tbody>
              {envVars.map((v) => (
                <tr key={v.id} className="border-t">
                  <td className="px-3 py-2 font-mono text-xs">{v.name}</td>
                  <td className="px-3 py-2 text-xs text-muted-foreground">{v.description}</td>
                  <td className="px-3 py-2 text-xs text-center">{v.position}</td>
                  <td className="px-2 py-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="w-6 h-6"
                      onClick={() => setDeleteTargetId(v.id)}
                    >
                      <Trash2 className="w-3 h-3 text-destructive" />
                    </Button>
                  </td>
                </tr>
              ))}
              {newRow && (
                <tr className="border-t bg-muted/20">
                  <td className="px-2 py-1">
                    <Input
                      className="h-7 text-xs font-mono"
                      placeholder="MY_VAR"
                      value={newRow.name}
                      onChange={(e) => setNewRow({ ...newRow, name: e.target.value.toUpperCase() })}
                      onKeyDown={(e) => { if (e.key === "Enter") handleAdd(); if (e.key === "Escape") setNewRow(null); }}
                      autoFocus
                    />
                  </td>
                  <td className="px-2 py-1">
                    <Input
                      className="h-7 text-xs"
                      placeholder={t("infra.env_var_description_placeholder")}
                      value={newRow.description}
                      onChange={(e) => setNewRow({ ...newRow, description: e.target.value })}
                    />
                  </td>
                  <td className="px-2 py-1">
                    <Input
                      className="h-7 text-xs w-14"
                      type="number"
                      value={newRow.position}
                      onChange={(e) => setNewRow({ ...newRow, position: parseInt(e.target.value, 10) || 0 })}
                    />
                  </td>
                  <td className="px-2 py-1">
                    <div className="flex gap-1">
                      <Button variant="ghost" size="icon" className="w-6 h-6" onClick={handleAdd}>
                        <Check className="w-3 h-3 text-green-600" />
                      </Button>
                      <Button variant="ghost" size="icon" className="w-6 h-6" onClick={() => setNewRow(null)}>
                        <X className="w-3 h-3" />
                      </Button>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      <ConfirmDialog
        open={deleteTargetId !== null}
        onOpenChange={(o) => { if (!o) setDeleteTargetId(null); }}
        title={t("infra.env_var_delete_title")}
        description={t("infra.env_var_delete_message", { name: deleteTarget?.name ?? "" })}
        onConfirm={async () => {
          if (!deleteTargetId) return;
          try {
            await remove.mutateAsync(deleteTargetId);
            setDeleteTargetId(null);
            toast.success(t("infra.env_var_deleted"));
          } catch {
            toast.error(t("infra.env_var_delete_error"));
          }
        }}
      />
    </div>
  );
}
```

- [ ] **Step 2: Créer le test**

```tsx
// frontend/src/components/__tests__/NamedTypeEnvVarsSection.test.tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NamedTypeEnvVarsSection } from "@/components/NamedTypeEnvVarsSection";
import * as infraEnvVarsApi from "@/lib/infraEnvVarsApi";

vi.mock("@/lib/infraEnvVarsApi");
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string, opts?: Record<string, string>) => opts ? `${k}:${JSON.stringify(opts)}` : k }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const NAMED_TYPE_ID = "nt-1";

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.mocked(infraEnvVarsApi.namedTypeEnvVarsApi.list).mockResolvedValue([]);
});

describe("NamedTypeEnvVarsSection", () => {
  it("affiche le message vide si aucune variable", async () => {
    render(<NamedTypeEnvVarsSection namedTypeId={NAMED_TYPE_ID} />, { wrapper });
    await waitFor(() => {
      expect(screen.getByText("infra.env_vars_empty")).toBeInTheDocument();
    });
  });

  it("affiche les variables existantes", async () => {
    vi.mocked(infraEnvVarsApi.namedTypeEnvVarsApi.list).mockResolvedValue([
      { id: "ev-1", named_type_id: NAMED_TYPE_ID, name: "MY_VAR", description: "desc", position: 0, created_at: "", updated_at: "" },
    ]);
    render(<NamedTypeEnvVarsSection namedTypeId={NAMED_TYPE_ID} />, { wrapper });
    await waitFor(() => {
      expect(screen.getByText("MY_VAR")).toBeInTheDocument();
    });
  });

  it("affiche la ligne d'ajout au clic sur Ajouter", async () => {
    render(<NamedTypeEnvVarsSection namedTypeId={NAMED_TYPE_ID} />, { wrapper });
    await waitFor(() => screen.getByText("infra.env_var_add_button"));
    await userEvent.click(screen.getByText("infra.env_var_add_button"));
    expect(screen.getByPlaceholderText("MY_VAR")).toBeInTheDocument();
  });

  it("appelle create et ferme la ligne après soumission valide", async () => {
    vi.mocked(infraEnvVarsApi.namedTypeEnvVarsApi.create).mockResolvedValue({
      id: "ev-2", named_type_id: NAMED_TYPE_ID, name: "NEW_VAR", description: "", position: 0, created_at: "", updated_at: "",
    });
    render(<NamedTypeEnvVarsSection namedTypeId={NAMED_TYPE_ID} />, { wrapper });
    await waitFor(() => screen.getByText("infra.env_var_add_button"));
    await userEvent.click(screen.getByText("infra.env_var_add_button"));
    await userEvent.type(screen.getByPlaceholderText("MY_VAR"), "NEW_VAR");
    await userEvent.keyboard("{Enter}");
    await waitFor(() => {
      expect(infraEnvVarsApi.namedTypeEnvVarsApi.create).toHaveBeenCalledWith(NAMED_TYPE_ID, expect.objectContaining({ name: "NEW_VAR" }));
    });
  });
});
```

- [ ] **Step 3: Lancer les tests**

```bash
cd frontend && npm test -- NamedTypeEnvVarsSection
```

Expected: tous PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/NamedTypeEnvVarsSection.tsx frontend/src/components/__tests__/NamedTypeEnvVarsSection.test.tsx
git commit -m "feat(frontend): NamedTypeEnvVarsSection + tests"
```

---

## Task 9: Composant `MachineEnvVarsSection` + tests

**Files:**
- Create: `frontend/src/components/MachineEnvVarsSection.tsx`
- Create: `frontend/src/components/__tests__/MachineEnvVarsSection.test.tsx`

**Contexte:** Ce composant affiche toutes les env vars du contrat de la machine (valeur vide si non remplies). L'indicateur de status côté client : `🔴` si vide, `🟠` si contient `${` (référence probablement non résolue), `🟢` sinon. Le composant `StatusIndicator` est dans `@/components/StatusIndicator`. Un seul bouton "Enregistrer" pour tout le bloc (pas d'édition ligne à ligne).

- [ ] **Step 1: Créer `MachineEnvVarsSection.tsx`**

```tsx
// frontend/src/components/MachineEnvVarsSection.tsx
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { useMachineEnvVars, useMachineEnvVarsUpsert } from "@/hooks/useInfraEnvVars";
import { StatusIndicator, type IndicatorStatus } from "@/components/StatusIndicator";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

function valueStatus(value: string): IndicatorStatus {
  if (!value) return "missing";
  if (value.includes("${")) return "empty";
  return "ok";
}

export function MachineEnvVarsSection({ machineId }: { machineId: string }) {
  const { t } = useTranslation();
  const { data: envVars = [], isLoading } = useMachineEnvVars(machineId);
  const upsert = useMachineEnvVarsUpsert(machineId);
  const [values, setValues] = useState<Record<string, string>>({});

  useEffect(() => {
    if (envVars.length > 0) {
      const initial: Record<string, string> = {};
      for (const ev of envVars) initial[ev.named_type_env_var_id] = ev.value;
      setValues(initial);
    }
  }, [envVars]);

  if (isLoading) return <p className="text-xs text-muted-foreground">…</p>;

  if (envVars.length === 0) {
    return <p className="text-xs text-muted-foreground italic">{t("infra.machine_env_vars_empty")}</p>;
  }

  async function handleSave() {
    try {
      await upsert.mutateAsync({ values });
      toast.success(t("infra.machine_env_vars_saved"));
    } catch {
      toast.error(t("infra.machine_env_vars_save_error"));
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-sm font-medium">{t("infra.machine_env_vars_title")}</p>
      <div className="space-y-2">
        {envVars.map((ev) => {
          const val = values[ev.named_type_env_var_id] ?? ev.value;
          return (
            <div key={ev.id} className="grid grid-cols-[auto_1fr_24px] gap-2 items-center">
              <div className="min-w-0">
                <p className="text-xs font-mono font-medium">{ev.name}</p>
                {ev.description && (
                  <p className="text-[10px] text-muted-foreground">{ev.description}</p>
                )}
              </div>
              <Input
                className="h-7 text-xs font-mono"
                placeholder={t("infra.machine_env_var_value_placeholder")}
                value={val}
                onChange={(e) => setValues({ ...values, [ev.named_type_env_var_id]: e.target.value })}
              />
              <StatusIndicator status={valueStatus(val)} label={ev.name} />
            </div>
          );
        })}
      </div>
      <Button size="sm" onClick={handleSave} disabled={upsert.isPending}>
        {upsert.isPending ? "…" : t("infra.machine_env_vars_save_button")}
      </Button>
    </div>
  );
}
```

- [ ] **Step 2: Créer le test**

```tsx
// frontend/src/components/__tests__/MachineEnvVarsSection.test.tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MachineEnvVarsSection } from "@/components/MachineEnvVarsSection";
import * as infraEnvVarsApi from "@/lib/infraEnvVarsApi";

vi.mock("@/lib/infraEnvVarsApi");
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const MACHINE_ID = "m-1";

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe("MachineEnvVarsSection", () => {
  beforeEach(() => {
    vi.mocked(infraEnvVarsApi.machineEnvVarsApi.list).mockResolvedValue([]);
  });

  it("affiche le message vide si aucune variable dans le contrat", async () => {
    render(<MachineEnvVarsSection machineId={MACHINE_ID} />, { wrapper });
    await waitFor(() => {
      expect(screen.getByText("infra.machine_env_vars_empty")).toBeInTheDocument();
    });
  });

  it("affiche les variables avec leur valeur courante", async () => {
    vi.mocked(infraEnvVarsApi.machineEnvVarsApi.list).mockResolvedValue([
      { id: "mv-1", machine_id: MACHINE_ID, named_type_env_var_id: "ev-1", name: "HOST", description: "The host", value: "example.com", created_at: "", updated_at: "" },
    ]);
    render(<MachineEnvVarsSection machineId={MACHINE_ID} />, { wrapper });
    await waitFor(() => {
      expect(screen.getByDisplayValue("example.com")).toBeInTheDocument();
    });
  });

  it("appelle upsert au clic Enregistrer", async () => {
    vi.mocked(infraEnvVarsApi.machineEnvVarsApi.list).mockResolvedValue([
      { id: "mv-1", machine_id: MACHINE_ID, named_type_env_var_id: "ev-1", name: "HOST", description: "", value: "", created_at: "", updated_at: "" },
    ]);
    vi.mocked(infraEnvVarsApi.machineEnvVarsApi.upsert).mockResolvedValue([]);
    render(<MachineEnvVarsSection machineId={MACHINE_ID} />, { wrapper });
    await waitFor(() => screen.getByText("infra.machine_env_vars_save_button"));
    const input = screen.getByPlaceholderText("infra.machine_env_var_value_placeholder");
    await userEvent.type(input, "new-value");
    await userEvent.click(screen.getByText("infra.machine_env_vars_save_button"));
    await waitFor(() => {
      expect(infraEnvVarsApi.machineEnvVarsApi.upsert).toHaveBeenCalledWith(
        MACHINE_ID,
        expect.objectContaining({ values: expect.objectContaining({ "ev-1": "new-value" }) }),
      );
    });
  });
});
```

- [ ] **Step 3: Lancer les tests**

```bash
cd frontend && npm test -- MachineEnvVarsSection
```

Expected: tous PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/MachineEnvVarsSection.tsx frontend/src/components/__tests__/MachineEnvVarsSection.test.tsx
git commit -m "feat(frontend): MachineEnvVarsSection + tests"
```

---

## Task 10: Intégration `InfraNamedTypesPage`

**Files:**
- Modify: `frontend/src/pages/InfraNamedTypesPage.tsx`

**Contexte:** Le dialog d'édition d'une variante typée s'appelle `NamedTypeDialog`. Il reçoit `initial: InfraNamedType | null`. Quand `initial` est défini (édition), on affiche la section `NamedTypeEnvVarsSection` avec l'ID du named type. Elle ne s'affiche pas en mode création (l'ID n'existe pas encore). Ajouter la section après le formulaire existant dans le `DialogContent`.

- [ ] **Step 1: Ajouter l'import de `NamedTypeEnvVarsSection` en haut du fichier**

Dans `frontend/src/pages/InfraNamedTypesPage.tsx`, ajouter après les autres imports de composants :

```tsx
import { NamedTypeEnvVarsSection } from "@/components/NamedTypeEnvVarsSection";
```

- [ ] **Step 2: Localiser le composant `NamedTypeDialog` dans le fichier et ajouter la section**

Trouver le bloc `DialogContent` dans `NamedTypeDialog` (chercher la balise `<DialogContent`), et ajouter `<NamedTypeEnvVarsSection>` conditionnellement à la fin du contenu du dialog, juste avant le `<DialogFooter>` :

```tsx
{initial && (
  <div className="border-t pt-4 mt-4">
    <NamedTypeEnvVarsSection namedTypeId={initial.id} />
  </div>
)}
```

- [ ] **Step 3: Vérifier la compilation**

```bash
cd frontend && npx tsc --noEmit
```

Expected: aucune erreur.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/InfraNamedTypesPage.tsx
git commit -m "feat(frontend): NamedTypeEnvVarsSection intégré dans InfraNamedTypesPage"
```

---

## Task 11: Intégration `InfraMachinesPage`

**Files:**
- Modify: `frontend/src/pages/InfraMachinesPage.tsx`

**Contexte:** Le dialog d'édition d'une machine doit afficher `MachineEnvVarsSection`. Chercher le dialog d'édition dans `InfraMachinesPage.tsx` (probablement un `Dialog` avec un state `editTarget`). La section est ajoutée conditionnellement quand `editTarget` est défini, dans une zone séparée du formulaire.

- [ ] **Step 1: Ajouter l'import**

```tsx
import { MachineEnvVarsSection } from "@/components/MachineEnvVarsSection";
```

- [ ] **Step 2: Localiser le dialog d'édition et ajouter la section**

Dans le `DialogContent` du dialog d'édition machine, ajouter après les champs existants (avant `DialogFooter`) :

```tsx
{editTarget && (
  <div className="border-t pt-4 mt-4">
    <MachineEnvVarsSection machineId={editTarget.id} />
  </div>
)}
```

- [ ] **Step 3: Vérifier**

```bash
cd frontend && npx tsc --noEmit
```

Expected: aucune erreur.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/InfraMachinesPage.tsx
git commit -m "feat(frontend): MachineEnvVarsSection intégré dans InfraMachinesPage"
```

---

## Task 12: Bannière check projet dans `ProjectDetailPage`

**Files:**
- Modify: `frontend/src/pages/ProjectDetailPage.tsx`

**Contexte:** `ProjectDetailPage` est dans `frontend/src/pages/ProjectDetailPage.tsx`. Il reçoit `projectId` via `useParams`. Il faut ajouter un hook `useProjectEnvVarsCheck(projectId)` et afficher une bannière rouge si `total_missing > 0`. La bannière liste les scripts concernés et les variables manquantes.

- [ ] **Step 1: Ajouter l'import**

Dans `frontend/src/pages/ProjectDetailPage.tsx`, ajouter :

```tsx
import { useProjectEnvVarsCheck } from "@/hooks/useInfraEnvVars";
```

- [ ] **Step 2: Ajouter le hook après les autres hooks**

```tsx
const envVarsCheck = useProjectEnvVarsCheck(projectId);
```

- [ ] **Step 3: Ajouter la bannière dans le JSX**

Localiser le contenu principal de la page (après `<PageHeader>`) et ajouter la bannière conditionnelle :

```tsx
{envVarsCheck.data && envVarsCheck.data.total_missing > 0 && (
  <div className="rounded-md border border-destructive/50 bg-destructive/10 px-4 py-3 text-sm">
    <p className="font-medium text-destructive">
      {t("projects.env_vars_missing_banner", { count: String(envVarsCheck.data.total_missing) })}
    </p>
    <ul className="mt-2 space-y-1">
      {envVarsCheck.data.items.map((item) => (
        <li key={item.group_script_id} className="text-xs text-muted-foreground">
          <span className="font-mono">{item.script_name}</span>
          {" — "}
          {item.missing_env_vars.join(", ")}
          {" ("}
          {item.group_name}
          {")"}
        </li>
      ))}
    </ul>
  </div>
)}
```

- [ ] **Step 4: Vérifier**

```bash
cd frontend && npx tsc --noEmit
```

Expected: aucune erreur.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/ProjectDetailPage.tsx
git commit -m "feat(frontend): bannière env vars manquantes dans ProjectDetailPage"
```

---

## Task 13: i18n FR + EN + sanity check final

**Files:**
- Modify: `frontend/src/i18n/fr.json`
- Modify: `frontend/src/i18n/en.json`

**Contexte:** Les clés i18n doivent être ajoutées sous un préfixe cohérent. Chercher la section `"infra"` dans `fr.json` et `en.json` pour trouver où l'ajouter. Chercher la section `"projects"` pour la bannière.

- [ ] **Step 1: Ajouter les clés dans `fr.json`**

Dans la section `"infra"` de `frontend/src/i18n/fr.json`, ajouter :

```json
"env_vars_title": "Variables d'environnement",
"env_var_add_button": "Ajouter",
"env_vars_empty": "Aucune variable d'environnement déclarée.",
"env_var_col_name": "Nom",
"env_var_col_description": "Description",
"env_var_col_position": "Pos.",
"env_var_invalid_name": "Le nom doit respecter le format A-Z_0-9 (ex: MY_VAR).",
"env_var_added": "Variable ajoutée.",
"env_var_add_error": "Erreur lors de l'ajout.",
"env_var_delete_title": "Supprimer la variable",
"env_var_delete_message": "Supprimer «{{name}}» ? Les valeurs renseignées sur les machines seront également supprimées.",
"env_var_deleted": "Variable supprimée.",
"env_var_delete_error": "Erreur lors de la suppression.",
"env_var_description_placeholder": "Description (optionnel)",
"machine_env_vars_title": "Variables d'environnement",
"machine_env_vars_empty": "Aucune variable déclarée pour cette variante.",
"machine_env_vars_save_button": "Enregistrer",
"machine_env_vars_saved": "Variables enregistrées.",
"machine_env_vars_save_error": "Erreur lors de l'enregistrement.",
"machine_env_var_value_placeholder": "valeur ou ${vault://VAULT:KEY}"
```

Dans la section `"projects"`, ajouter :

```json
"env_vars_missing_banner": "{{count}} variable(s) d'environnement manquante(s) pour ce projet."
```

- [ ] **Step 2: Ajouter les clés dans `en.json`**

Dans la section `"infra"` de `frontend/src/i18n/en.json`, ajouter :

```json
"env_vars_title": "Environment variables",
"env_var_add_button": "Add",
"env_vars_empty": "No environment variables declared.",
"env_var_col_name": "Name",
"env_var_col_description": "Description",
"env_var_col_position": "Pos.",
"env_var_invalid_name": "Name must match format A-Z_0-9 (e.g. MY_VAR).",
"env_var_added": "Variable added.",
"env_var_add_error": "Failed to add variable.",
"env_var_delete_title": "Delete variable",
"env_var_delete_message": "Delete «{{name}}»? Values set on machines will also be deleted.",
"env_var_deleted": "Variable deleted.",
"env_var_delete_error": "Failed to delete variable.",
"env_var_description_placeholder": "Description (optional)",
"machine_env_vars_title": "Environment variables",
"machine_env_vars_empty": "No variables declared for this variant.",
"machine_env_vars_save_button": "Save",
"machine_env_vars_saved": "Variables saved.",
"machine_env_vars_save_error": "Failed to save variables.",
"machine_env_var_value_placeholder": "value or ${vault://VAULT:KEY}"
```

Dans la section `"projects"`, ajouter :

```json
"env_vars_missing_banner": "{{count}} missing environment variable(s) for this project."
```

- [ ] **Step 3: Vérifier TypeScript strict + lint**

```bash
cd frontend && npx tsc --noEmit && npm run lint
```

Expected: aucune erreur.

- [ ] **Step 4: Lancer tous les tests frontend**

```bash
cd frontend && npm test
```

Expected: tous PASS.

- [ ] **Step 5: Lancer tous les tests backend**

```bash
cd backend && uv run pytest tests/services/test_infra_env_vars_service.py -v
```

Expected: tous PASS.

- [ ] **Step 6: Commit final**

```bash
git add frontend/src/i18n/fr.json frontend/src/i18n/en.json
git commit -m "feat(i18n): FR + EN — infra env vars + check projet"
```

---

## Self-Review checklist (post-implémentation)

Avant de marquer terminé, vérifier :

- [ ] `npx tsc --noEmit` sans erreur
- [ ] `npm run lint` sans erreur
- [ ] `uv run pytest tests/services/test_infra_env_vars_service.py -v` tous PASS
- [ ] `npm test` tous PASS
- [ ] `uv run python -c "from agflow.main import app; print('OK')"` → OK
- [ ] Chaque endpoint listé dans la spec (7 endpoints) est bien dans un router
- [ ] La migration 121 applique proprement depuis zéro (reset_schema_and_migrate le teste)
