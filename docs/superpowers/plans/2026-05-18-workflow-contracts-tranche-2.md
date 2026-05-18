# Workflow Contracts — Tranche 2 (matérialisation resources runtime)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Matérialiser les resources par-(runtime × instance) dans une nouvelle table `project_runtime_instances`, et remplacer le sync simulé de T1 par un vrai worker provisioning qui rend les `connection_params` Jinja et marque les statuts par-runtime. Conforme contrat v5 §3.4 (`resource_id` UUID v4 stable par runtime).

**Architecture:** Nouvelle table `project_runtime_instances` symétrique à `project_group_runtimes` (pivot N-N entre `project_runtimes` et `instances`). Le `id` de cette table = `resource_id` du contrat v5. Le `POST /projects/{id}/runtimes` crée le runtime (`status='pending'`) **et** les `project_runtime_instances` (`provisioning_status='provisioning'`) de manière atomique. Un worker asyncio (`provisioning_worker`) tourne dans le lifespan FastAPI, poll les runtimes pending workflow (`user_id IS NULL`), rend Jinja sur `connection_params` + `setup_steps`, marque `provisioning_status='ready'` (ou `pending_setup`/`failed`). Le `GET /api/admin/project-runtimes/{id}/resources` lit la nouvelle table avec JOIN `instances` pour exposer `mcp_bindings` (qui restent sur le template). Aucune duplication des `mcp_bindings` en DB — ils sont rendus à la volée car définis par le `catalog_id` du produit.

**Tech Stack:** Python 3.12 + FastAPI lifespan + asyncpg + Pydantic v2 + Jinja2 (déjà dans `pyproject.toml`) + structlog + pytest + pytest-asyncio. Backend uniquement.

**Spec de référence :** `docs/contracts/docker-orchestration-flow.md` §3.3, §3.4. Glossaire dans `docs/db/tables.md`.

**Branche cible :** `dev`. Pas de feature branch.

**Décisions de cadrage (figées 2026-05-18) :**
- Nouvelle table dédiée (option R1) — symétrique à `project_group_runtimes`.
- Worker asyncio dans le process FastAPI (pas de container séparé).
- `mcp_bindings` non dupliqués en DB — JOIN `instances` au moment de `GET /resources`.
- `setup_steps` matérialisés (copie rendue par runtime, statut évolutif).
- Discriminant worker workflow vs SaaS Phase 1 : `project_runtimes.user_id IS NULL`.
- Cleanup `instances` (retrait `provisioning_status`, `service_url`) : **différé tranche 2 bis**.

**Note tests** :
- Tests pytest API peuvent retourner DONE_WITH_CONCERNS sur dev Windows (LXC injoignable), même politique que T1.
- Validation finale via `./scripts/run-test.sh` à T9.

**Note Jinja sécurité** : le worker rend du Jinja à partir de strings stockées en DB par l'admin (via l'éditeur de produits). Pas d'input utilisateur final. SandboxedEnvironment recommandé pour la défense en profondeur.

---

## Structure des fichiers (vue d'ensemble)

### Backend (4 nouveaux + 3 modifs)

| Fichier | Responsabilité | Lignes |
|---|---|---|
| `backend/migrations/002_project_runtime_instances.sql` (nouveau) | CREATE TABLE + indexes | ~30 |
| `backend/src/agflow/services/project_runtime_instances_service.py` (nouveau) | CRUD : create_bulk, list_by_runtime, get_by_id, mark_status, mark_failed | ~150 |
| `backend/src/agflow/services/jinja_render.py` (nouveau) | Helper `render_jsonb_jinja(value, context)` récursif + SandboxedEnvironment | ~80 |
| `backend/src/agflow/workers/provisioning_worker.py` (nouveau) | Worker asyncio : poll pending workflow runtimes, render Jinja, UPDATE status | ~180 |
| `backend/src/agflow/services/workflow_provisioning_service.py` (modif) | `provision_runtime` : INSERT runtime + bulk INSERT instances ; `get_resources` : lit nouvelle table avec JOIN | +60 / -30 |
| `backend/src/agflow/api/admin/workflow_runtimes.py` (modif) | Mapping DTO `ResourceState` depuis le nouveau format | +20 |
| `backend/src/agflow/main.py` (modif) | Lifespan : `asyncio.create_task(provisioning_worker_loop())` + cancel sur shutdown | +8 |
| `backend/src/agflow/schemas/workflow.py` (modif) | Ajout `mcp_bindings` à `ResourceState` (déjà présent partiellement) | +2 |

### Tests (5 fichiers nouveaux)

| Fichier | Tests |
|---|---|
| `backend/tests/db/test_project_runtime_instances_present.py` | 3 : table existe, colonnes attendues, contraintes FK/CHECK |
| `backend/tests/services/test_project_runtime_instances_service.py` | 5 : create_bulk insère N rows, list_by_runtime, get_by_id, mark_status, mark_failed avec error_message |
| `backend/tests/services/test_jinja_render.py` | 6 : string simple, dict imbriqué, liste, valeur non-string ignorée, var manquante raise, sandbox bloque `__class__` |
| `backend/tests/services/test_workflow_provisioning_service.py` (existant — réécrit) | 4 : provision_runtime INSERT runtime+instances, status initial, get_resources expose resource_id, project inexistant raise |
| `backend/tests/workers/test_provisioning_worker.py` | 4 : claim pending workflow runtime, render Jinja réussi → status ready, var manquante → status failed + error_message, ignore runtimes SaaS (user_id NOT NULL) |

**Total : 22 tests pytest.**

---

## Tâche 1 — Migration 002 + test de présence

**Files:**
- Create: `backend/migrations/002_project_runtime_instances.sql`
- Create: `backend/tests/db/test_project_runtime_instances_present.py`

### Step 1 — Créer la migration

- [ ] Créer `backend/migrations/002_project_runtime_instances.sql` :

```sql
-- 002_project_runtime_instances.sql
--
-- Matérialisation des resources par-(runtime × instance) pour le contrat
-- workflow v5 §3.4. Le `id` de cette table devient le `resource_id` exposé
-- à ag.flow, stable par runtime et CASCADE avec lui.
--
-- Symétrique à project_group_runtimes (pivot N-N) mais à la granularité
-- instance individuelle. mcp_bindings ne sont pas dupliqués : ils restent
-- sur le template `instances` et sont lus via JOIN au moment du GET /resources.

CREATE TABLE project_runtime_instances (
    id uuid DEFAULT gen_random_uuid() NOT NULL PRIMARY KEY,
    project_runtime_id uuid NOT NULL REFERENCES project_runtimes(id) ON DELETE CASCADE,
    instance_id uuid NOT NULL REFERENCES instances(id) ON DELETE RESTRICT,
    connection_params jsonb,
    setup_steps jsonb DEFAULT '[]'::jsonb NOT NULL,
    provisioning_status varchar(32) NOT NULL DEFAULT 'provisioning',
    container_id text,
    service_url varchar,
    error_message text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT project_runtime_instances_status_check
        CHECK (provisioning_status IN ('provisioning','ready','pending_setup','failed')),
    UNIQUE (project_runtime_id, instance_id)
);

CREATE INDEX idx_pri_runtime ON project_runtime_instances(project_runtime_id);
CREATE INDEX idx_pri_status ON project_runtime_instances(provisioning_status);

CREATE TRIGGER set_updated_at_project_runtime_instances
    BEFORE UPDATE ON project_runtime_instances
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
```

### Step 2 — Écrire le test de présence

- [ ] Créer `backend/tests/db/test_project_runtime_instances_present.py` :

```python
"""Vérifie la présence et la structure de project_runtime_instances.

Garde-fou : la migration 002 doit être appliquée pour que T2 fonctionne.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_table_exists(fresh_db):
    row = await fresh_db.fetchrow(
        """
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'project_runtime_instances'
        """
    )
    assert row is not None, "table project_runtime_instances manquante"


async def test_columns_present(fresh_db):
    expected = {
        "id", "project_runtime_id", "instance_id",
        "connection_params", "setup_steps", "provisioning_status",
        "container_id", "service_url", "error_message",
        "created_at", "updated_at",
    }
    rows = await fresh_db.fetch(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'project_runtime_instances'
        """
    )
    found = {r["column_name"] for r in rows}
    missing = expected - found
    assert not missing, f"colonnes manquantes : {missing}"


async def test_check_constraint_provisioning_status(fresh_db):
    """Le CHECK constraint doit rejeter une valeur invalide."""
    import asyncpg

    # Crée un runtime + instance valides pour test FK
    runtime_id = await fresh_db.fetchval(
        """
        INSERT INTO projects (display_name) VALUES ('test-proj') RETURNING id
        """
    )
    runtime_id_real = await fresh_db.fetchval(
        """
        INSERT INTO project_runtimes (project_id, status, user_id)
        VALUES ($1, 'pending', NULL)
        RETURNING id
        """,
        runtime_id,
    )
    group_id = await fresh_db.fetchval(
        "INSERT INTO groups (project_id, name) VALUES ($1, 'g1') RETURNING id",
        runtime_id,
    )
    instance_id = await fresh_db.fetchval(
        """
        INSERT INTO instances (group_id, instance_name, catalog_id)
        VALUES ($1, 'i1', 'cat1') RETURNING id
        """,
        group_id,
    )

    with pytest.raises(asyncpg.CheckViolationError):
        await fresh_db.execute(
            """
            INSERT INTO project_runtime_instances
            (project_runtime_id, instance_id, provisioning_status)
            VALUES ($1, $2, 'invalid_status')
            """,
            runtime_id_real,
            instance_id,
        )
```

### Step 3 — Lancer test

- [ ] `cd backend && uv run pytest tests/db/test_project_runtime_instances_present.py -v`
- [ ] Attendu : **3 PASS** (DONE_WITH_CONCERNS acceptable si DB injoignable depuis Windows).

### Step 4 — Lint

- [ ] `cd backend && uv run ruff check backend/migrations/002_project_runtime_instances.sql tests/db/test_project_runtime_instances_present.py`

### Step 5 — Commit

```bash
git add backend/migrations/002_project_runtime_instances.sql \
        backend/tests/db/test_project_runtime_instances_present.py
git commit -m "feat(workflow-t2): migration 002 project_runtime_instances + test de présence"
```

---

## Tâche 2 — Service `project_runtime_instances_service.py`

**Files:**
- Create: `backend/src/agflow/services/project_runtime_instances_service.py`
- Create: `backend/tests/services/test_project_runtime_instances_service.py`

### Step 1 — Écrire les tests (failing)

- [ ] Créer `backend/tests/services/test_project_runtime_instances_service.py` :

```python
"""Tests de project_runtime_instances_service."""
from __future__ import annotations

from uuid import uuid4

import pytest

pytestmark = pytest.mark.asyncio


async def test_create_bulk_inserts_one_row_per_instance(
    fresh_db, mock_runtime_with_instances
):
    """create_bulk insère 1 row par instance template du projet."""
    from agflow.services import project_runtime_instances_service as pri

    runtime_id = mock_runtime_with_instances["runtime_id"]
    instance_ids = mock_runtime_with_instances["instance_ids"]

    created = await pri.create_bulk(
        project_runtime_id=runtime_id,
        instance_ids=instance_ids,
    )
    assert len(created) == len(instance_ids)
    for row in created:
        assert row["provisioning_status"] == "provisioning"
        assert row["project_runtime_id"] == runtime_id
        assert row["instance_id"] in instance_ids


async def test_list_by_runtime(fresh_db, mock_runtime_with_instances):
    from agflow.services import project_runtime_instances_service as pri

    runtime_id = mock_runtime_with_instances["runtime_id"]
    await pri.create_bulk(
        project_runtime_id=runtime_id,
        instance_ids=mock_runtime_with_instances["instance_ids"],
    )
    rows = await pri.list_by_runtime(project_runtime_id=runtime_id)
    assert len(rows) == len(mock_runtime_with_instances["instance_ids"])


async def test_get_by_id(fresh_db, mock_runtime_with_instances):
    from agflow.services import project_runtime_instances_service as pri

    runtime_id = mock_runtime_with_instances["runtime_id"]
    created = await pri.create_bulk(
        project_runtime_id=runtime_id,
        instance_ids=mock_runtime_with_instances["instance_ids"][:1],
    )
    pri_id = created[0]["id"]
    row = await pri.get_by_id(pri_id)
    assert row is not None
    assert row["id"] == pri_id


async def test_mark_status_ready(fresh_db, mock_runtime_with_instances):
    from agflow.services import project_runtime_instances_service as pri

    runtime_id = mock_runtime_with_instances["runtime_id"]
    created = await pri.create_bulk(
        project_runtime_id=runtime_id,
        instance_ids=mock_runtime_with_instances["instance_ids"][:1],
    )
    pri_id = created[0]["id"]
    await pri.mark_status(
        pri_id=pri_id,
        status="ready",
        connection_params={"url": "https://wiki.example.com"},
        setup_steps=[],
    )
    row = await pri.get_by_id(pri_id)
    assert row["provisioning_status"] == "ready"
    assert row["connection_params"] == {"url": "https://wiki.example.com"}


async def test_mark_failed_records_error(
    fresh_db, mock_runtime_with_instances
):
    from agflow.services import project_runtime_instances_service as pri

    runtime_id = mock_runtime_with_instances["runtime_id"]
    created = await pri.create_bulk(
        project_runtime_id=runtime_id,
        instance_ids=mock_runtime_with_instances["instance_ids"][:1],
    )
    pri_id = created[0]["id"]
    await pri.mark_failed(pri_id=pri_id, error_message="jinja var missing: hostname")
    row = await pri.get_by_id(pri_id)
    assert row["provisioning_status"] == "failed"
    assert "jinja var missing" in row["error_message"]
```

**Fixture `mock_runtime_with_instances`** : à ajouter dans `backend/tests/conftest.py` (si pas déjà présente). Doit créer :
- 1 projet
- 1 group
- N instances (template) avec `connection_params` portant des vars Jinja non rendues
- 1 project_runtime (`user_id NULL`, `status='pending'`)
- Retourner `{"runtime_id": ..., "project_id": ..., "instance_ids": [...]}`

### Step 2 — Verify fail

- [ ] `cd backend && uv run pytest tests/services/test_project_runtime_instances_service.py -v`
- [ ] Attendu : `ModuleNotFoundError: agflow.services.project_runtime_instances_service`.

### Step 3 — Écrire le service

- [ ] Créer `backend/src/agflow/services/project_runtime_instances_service.py` :

```python
"""CRUD de project_runtime_instances (matérialisation resources par runtime).

Symétrique à project_runtimes_service / project_group_runtimes mais à la
granularité instance individuelle. Le `id` de cette table = `resource_id`
exposé via le contrat workflow v5 §3.4.
"""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_all, fetch_one

_log = structlog.get_logger(__name__)


async def create_bulk(
    *,
    project_runtime_id: UUID,
    instance_ids: list[UUID],
) -> list[dict]:
    """Insère 1 row par instance_id avec status='provisioning'."""
    if not instance_ids:
        return []

    # asyncpg ne supporte pas executemany RETURNING — on boucle.
    created: list[dict] = []
    for instance_id in instance_ids:
        row = await fetch_one(
            """
            INSERT INTO project_runtime_instances
            (project_runtime_id, instance_id, provisioning_status)
            VALUES ($1, $2, 'provisioning')
            RETURNING id, project_runtime_id, instance_id, provisioning_status
            """,
            project_runtime_id,
            instance_id,
        )
        assert row is not None
        created.append(
            {
                "id": row["id"],
                "project_runtime_id": row["project_runtime_id"],
                "instance_id": row["instance_id"],
                "provisioning_status": row["provisioning_status"],
            }
        )

    _log.info(
        "workflow.runtime_instances.created_bulk",
        runtime_id=str(project_runtime_id),
        count=len(created),
    )
    return created


async def list_by_runtime(*, project_runtime_id: UUID) -> list[dict]:
    """Liste toutes les rows pour un runtime, JOIN instances pour catalog_id+mcp_bindings."""
    rows = await fetch_all(
        """
        SELECT
            pri.id, pri.project_runtime_id, pri.instance_id,
            pri.connection_params, pri.setup_steps, pri.provisioning_status,
            pri.container_id, pri.service_url, pri.error_message,
            pri.created_at, pri.updated_at,
            i.instance_name, i.catalog_id, i.mcp_bindings AS template_mcp_bindings
        FROM project_runtime_instances pri
        JOIN instances i ON i.id = pri.instance_id
        WHERE pri.project_runtime_id = $1
        ORDER BY pri.created_at
        """,
        project_runtime_id,
    )
    return [dict(r) for r in rows]


async def get_by_id(pri_id: UUID) -> dict | None:
    row = await fetch_one(
        """
        SELECT
            pri.id, pri.project_runtime_id, pri.instance_id,
            pri.connection_params, pri.setup_steps, pri.provisioning_status,
            pri.container_id, pri.service_url, pri.error_message,
            i.instance_name, i.catalog_id, i.mcp_bindings AS template_mcp_bindings
        FROM project_runtime_instances pri
        JOIN instances i ON i.id = pri.instance_id
        WHERE pri.id = $1
        """,
        pri_id,
    )
    return dict(row) if row else None


async def mark_status(
    *,
    pri_id: UUID,
    status: str,
    connection_params: dict[str, Any] | None = None,
    setup_steps: list[dict[str, Any]] | None = None,
    container_id: str | None = None,
    service_url: str | None = None,
) -> None:
    """Marque le statut + écrit les champs rendus. status ∈ {ready, pending_setup}."""
    await execute(
        """
        UPDATE project_runtime_instances
        SET provisioning_status = $1,
            connection_params = COALESCE($2::jsonb, connection_params),
            setup_steps = COALESCE($3::jsonb, setup_steps),
            container_id = COALESCE($4, container_id),
            service_url = COALESCE($5, service_url),
            error_message = NULL
        WHERE id = $6
        """,
        status,
        json.dumps(connection_params) if connection_params is not None else None,
        json.dumps(setup_steps) if setup_steps is not None else None,
        container_id,
        service_url,
        pri_id,
    )
    _log.info("workflow.runtime_instance.status_set", pri_id=str(pri_id), status=status)


async def mark_failed(*, pri_id: UUID, error_message: str) -> None:
    await execute(
        """
        UPDATE project_runtime_instances
        SET provisioning_status = 'failed',
            error_message = $1
        WHERE id = $2
        """,
        error_message,
        pri_id,
    )
    _log.warning(
        "workflow.runtime_instance.failed",
        pri_id=str(pri_id),
        error=error_message,
    )
```

### Step 4 — Re-lancer

- [ ] `cd backend && uv run pytest tests/services/test_project_runtime_instances_service.py -v`
- [ ] Attendu : **5 PASS** (DONE_WITH_CONCERNS acceptable si DB injoignable).

### Step 5 — Lint

- [ ] `cd backend && uv run ruff check src/agflow/services/project_runtime_instances_service.py tests/services/test_project_runtime_instances_service.py`

### Step 6 — Commit

```bash
git add backend/src/agflow/services/project_runtime_instances_service.py \
        backend/tests/services/test_project_runtime_instances_service.py
git commit -m "feat(workflow-t2): project_runtime_instances_service (CRUD + bulk insert)"
```

---

## Tâche 3 — Helper Jinja rendering récursif

**Files:**
- Create: `backend/src/agflow/services/jinja_render.py`
- Create: `backend/tests/services/test_jinja_render.py`

### Step 1 — Écrire les tests

- [ ] Créer `backend/tests/services/test_jinja_render.py` :

```python
"""Tests du helper Jinja récursif pour rendre les jsonb du workflow."""
from __future__ import annotations

import pytest

from agflow.services.jinja_render import (
    JinjaRenderError,
    render_jsonb_jinja,
)


def test_render_simple_string():
    out = render_jsonb_jinja("https://{{ runtime.host }}", {"runtime": {"host": "x.com"}})
    assert out == "https://x.com"


def test_render_dict_nested():
    src = {
        "url": "https://{{ runtime.host }}",
        "auth": {"token": "{{ runtime.token }}"},
    }
    ctx = {"runtime": {"host": "x.com", "token": "abc"}}
    out = render_jsonb_jinja(src, ctx)
    assert out == {"url": "https://x.com", "auth": {"token": "abc"}}


def test_render_list_of_strings():
    src = ["{{ runtime.host }}", "static", "{{ runtime.token }}"]
    out = render_jsonb_jinja(src, {"runtime": {"host": "x", "token": "y"}})
    assert out == ["x", "static", "y"]


def test_non_string_values_passthrough():
    src = {"port": 5432, "ssl": True, "name": "{{ runtime.host }}"}
    out = render_jsonb_jinja(src, {"runtime": {"host": "x"}})
    assert out == {"port": 5432, "ssl": True, "name": "x"}


def test_missing_var_raises():
    with pytest.raises(JinjaRenderError) as exc:
        render_jsonb_jinja("{{ runtime.missing }}", {"runtime": {}})
    assert "missing" in str(exc.value)


def test_sandbox_blocks_dunder_access():
    """SandboxedEnvironment doit refuser l'accès aux attributs __class__."""
    with pytest.raises(JinjaRenderError):
        render_jsonb_jinja(
            "{{ runtime.__class__.__name__ }}",
            {"runtime": {"x": 1}},
        )
```

### Step 2 — Verify fail

- [ ] `cd backend && uv run pytest tests/services/test_jinja_render.py -v`
- [ ] Attendu : `ModuleNotFoundError: agflow.services.jinja_render`.

### Step 3 — Écrire le helper

- [ ] Créer `backend/src/agflow/services/jinja_render.py` :

```python
"""Rendering Jinja récursif pour les jsonb workflow.

Parcourt récursivement les valeurs string d'un dict/list et applique Jinja2
dessus avec SandboxedEnvironment (défense en profondeur : pas d'accès aux
attributs spéciaux Python même si l'admin déclare du Jinja malicieux).

Variables non-string (int, bool, None) passent à travers sans modification.
"""
from __future__ import annotations

from typing import Any

from jinja2 import StrictUndefined
from jinja2.exceptions import SecurityError, TemplateError, UndefinedError
from jinja2.sandbox import SandboxedEnvironment


class JinjaRenderError(Exception):
    """Erreur de rendu Jinja (var manquante, sandbox violation, syntax)."""


_env = SandboxedEnvironment(
    undefined=StrictUndefined,
    autoescape=False,  # JSON values, pas du HTML
)


def render_jsonb_jinja(value: Any, context: dict[str, Any]) -> Any:
    """Render récursif. Strings → Jinja. Autres types → passthrough."""
    if isinstance(value, str):
        try:
            return _env.from_string(value).render(**context)
        except UndefinedError as exc:
            raise JinjaRenderError(f"jinja undefined var: {exc}") from exc
        except SecurityError as exc:
            raise JinjaRenderError(f"jinja sandbox violation: {exc}") from exc
        except TemplateError as exc:
            raise JinjaRenderError(f"jinja template error: {exc}") from exc
    if isinstance(value, dict):
        return {k: render_jsonb_jinja(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [render_jsonb_jinja(v, context) for v in value]
    return value
```

### Step 4 — Re-lancer

- [ ] `cd backend && uv run pytest tests/services/test_jinja_render.py -v`
- [ ] Attendu : **6 PASS**.

### Step 5 — Lint

- [ ] `cd backend && uv run ruff check src/agflow/services/jinja_render.py tests/services/test_jinja_render.py`

### Step 6 — Commit

```bash
git add backend/src/agflow/services/jinja_render.py \
        backend/tests/services/test_jinja_render.py
git commit -m "feat(workflow-t2): helper jinja_render (sandboxed + récursif jsonb)"
```

---

## Tâche 4 — Refacto `workflow_provisioning_service.provision_runtime`

**Files:**
- Modify: `backend/src/agflow/services/workflow_provisioning_service.py`
- Modify: `backend/tests/services/test_workflow_provisioning_service.py` (tests existants à mettre à jour)

### Step 1 — Mettre à jour les tests

- [ ] Réécrire `backend/tests/services/test_workflow_provisioning_service.py` :

```python
"""Tests de workflow_provisioning_service après refacto T2."""
from __future__ import annotations

from uuid import uuid4

import pytest

pytestmark = pytest.mark.asyncio


async def test_provision_runtime_inserts_runtime_pending(
    fresh_db, mock_project_with_resources
):
    """provision_runtime crée le runtime avec status='pending' (worker reprendra)."""
    from agflow.services import workflow_provisioning_service as wp

    project_id = mock_project_with_resources["project_id"]
    runtime_id = await wp.provision_runtime(project_id=project_id)

    row = await fresh_db.fetchrow(
        "SELECT status, user_id FROM project_runtimes WHERE id = $1",
        runtime_id,
    )
    assert row is not None
    assert row["status"] == "pending"  # plus de UPDATE deployed sync
    assert row["user_id"] is None  # workflow m2m


async def test_provision_runtime_creates_runtime_instances(
    fresh_db, mock_project_with_resources
):
    """Pour chaque instance template, une row project_runtime_instances est créée."""
    from agflow.services import workflow_provisioning_service as wp

    project_id = mock_project_with_resources["project_id"]
    expected_count = mock_project_with_resources["resources_count"]
    runtime_id = await wp.provision_runtime(project_id=project_id)

    count = await fresh_db.fetchval(
        """
        SELECT COUNT(*) FROM project_runtime_instances
        WHERE project_runtime_id = $1
        """,
        runtime_id,
    )
    assert count == expected_count


async def test_provision_runtime_unknown_project_raises(fresh_db):
    from agflow.services import workflow_provisioning_service as wp

    with pytest.raises(wp.ProjectNotFoundError):
        await wp.provision_runtime(project_id=uuid4())


async def test_get_resources_returns_resource_id_stable_per_runtime(
    fresh_db, mock_project_with_resources
):
    """Le resource_id = project_runtime_instances.id, stable par runtime."""
    from agflow.services import workflow_provisioning_service as wp

    project_id = mock_project_with_resources["project_id"]
    runtime_id_a = await wp.provision_runtime(project_id=project_id)
    runtime_id_b = await wp.provision_runtime(project_id=project_id)

    res_a = await wp.get_resources(runtime_id=runtime_id_a)
    res_b = await wp.get_resources(runtime_id=runtime_id_b)

    # Les resource_id sont distincts entre les 2 runtimes
    ids_a = {r["resource_id"] for r in res_a}
    ids_b = {r["resource_id"] for r in res_b}
    assert ids_a.isdisjoint(ids_b)
    assert len(ids_a) == mock_project_with_resources["resources_count"]
```

### Step 2 — Réécrire le service

- [ ] Remplacer `backend/src/agflow/services/workflow_provisioning_service.py` par :

```python
"""Provisioning workflow v5 — refacto tranche 2.

Changement vs T1 :
- `provision_runtime` crée le runtime (status='pending') + les rows
  project_runtime_instances (provisioning_status='provisioning') de manière
  atomique. Le worker provisioning_worker reprend ensuite pour rendre Jinja
  et marquer status='ready'/'failed'.
- `get_resources` lit project_runtime_instances avec JOIN instances pour
  exposer les mcp_bindings du template + connection_params rendus du runtime.
"""
from __future__ import annotations

from uuid import UUID

import structlog

from agflow.db.pool import fetch_all, fetch_one
from agflow.services import project_runtime_instances_service as pri_service

_log = structlog.get_logger(__name__)


class ProjectNotFoundError(Exception):
    pass


async def provision_runtime(*, project_id: UUID) -> UUID:
    """Crée un project_runtime (pending) + ses project_runtime_instances.

    Le worker provisioning_worker reprendra ensuite pour rendre Jinja et
    marquer le runtime + ses instances comme ready/failed.

    Retourne le runtime_id.
    """
    project = await fetch_one("SELECT id FROM projects WHERE id = $1", project_id)
    if project is None:
        raise ProjectNotFoundError(f"project {project_id} not found")

    # Liste les instances template du projet (via groups)
    instance_rows = await fetch_all(
        """
        SELECT i.id
        FROM instances i
        JOIN groups g ON g.id = i.group_id
        WHERE g.project_id = $1
        ORDER BY i.created_at
        """,
        project_id,
    )
    instance_ids = [r["id"] for r in instance_rows]

    # INSERT runtime status='pending', user_id NULL = discriminant workflow m2m
    runtime_row = await fetch_one(
        """
        INSERT INTO project_runtimes (project_id, status, user_id)
        VALUES ($1, 'pending', NULL)
        RETURNING id
        """,
        project_id,
    )
    assert runtime_row is not None
    runtime_id: UUID = runtime_row["id"]

    # Bulk INSERT des rows par instance avec status='provisioning'
    await pri_service.create_bulk(
        project_runtime_id=runtime_id,
        instance_ids=instance_ids,
    )

    _log.info(
        "workflow.runtime.provisioned",
        runtime_id=str(runtime_id),
        project_id=str(project_id),
        instance_count=len(instance_ids),
    )
    return runtime_id


async def get_resources(*, runtime_id: UUID) -> list[dict]:
    """Liste les resources matérialisées d'un runtime au format contrat v5.

    Retourne :
    - resource_id (= project_runtime_instances.id)
    - type (= instances.catalog_id)
    - name (= instances.instance_name)
    - status (= project_runtime_instances.provisioning_status)
    - connection_params (rendus si status=ready)
    - mcp_bindings (du template, rendus à la volée si nécessaire)
    - setup_steps (rendus si status=pending_setup)
    """
    rows = await pri_service.list_by_runtime(project_runtime_id=runtime_id)
    return [
        {
            "resource_id": r["id"],
            "type": r["catalog_id"],
            "name": r["instance_name"],
            "status": r["provisioning_status"],
            "connection_params": r["connection_params"],
            "mcp_bindings": r["template_mcp_bindings"],
            "setup_steps": r["setup_steps"],
            "error_message": r["error_message"],
        }
        for r in rows
    ]
```

### Step 3 — Mettre à jour la fixture `mock_project_with_resources`

- [ ] Vérifier `backend/tests/conftest.py` et adapter la fixture pour qu'elle retourne `resources_count` (nombre d'instances template insérées) en plus de `project_id`.

### Step 4 — Re-lancer

- [ ] `cd backend && uv run pytest tests/services/test_workflow_provisioning_service.py -v`
- [ ] Attendu : **4 PASS**.

### Step 5 — Lint

- [ ] `cd backend && uv run ruff check src/agflow/services/workflow_provisioning_service.py tests/services/test_workflow_provisioning_service.py`

### Step 6 — Commit

```bash
git add backend/src/agflow/services/workflow_provisioning_service.py \
        backend/tests/services/test_workflow_provisioning_service.py \
        backend/tests/conftest.py
git commit -m "refactor(workflow-t2): provision_runtime crée pri rows + get_resources lit nouvelle table"
```

---

## Tâche 5 — Worker `provisioning_worker.py`

**Files:**
- Create: `backend/src/agflow/workers/provisioning_worker.py`
- Create: `backend/tests/workers/test_provisioning_worker.py`

### Step 1 — Écrire les tests

- [ ] Créer `backend/tests/workers/test_provisioning_worker.py` :

```python
"""Tests du provisioning_worker workflow."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_process_pending_renders_jinja_marks_ready(
    fresh_db, mock_pending_workflow_runtime
):
    """Le worker rend les connection_params Jinja et marque status='ready'."""
    from agflow.workers import provisioning_worker

    runtime_id = mock_pending_workflow_runtime["runtime_id"]
    await provisioning_worker.process_pending_runtimes()

    # Runtime passé à deployed
    runtime_row = await fresh_db.fetchrow(
        "SELECT status FROM project_runtimes WHERE id = $1", runtime_id
    )
    assert runtime_row["status"] == "deployed"

    # Instances passées à ready avec connection_params rendus
    pri_rows = await fresh_db.fetch(
        """
        SELECT provisioning_status, connection_params
        FROM project_runtime_instances
        WHERE project_runtime_id = $1
        """,
        runtime_id,
    )
    for r in pri_rows:
        assert r["provisioning_status"] == "ready"
        # vars Jinja remplacées (pas de '{{' dans le JSON rendu)
        assert "{{" not in str(r["connection_params"])


async def test_process_pending_marks_failed_on_jinja_error(
    fresh_db, mock_pending_workflow_runtime_with_bad_jinja
):
    """Une var Jinja manquante → instance.status='failed' + error_message."""
    from agflow.workers import provisioning_worker

    runtime_id = mock_pending_workflow_runtime_with_bad_jinja["runtime_id"]
    await provisioning_worker.process_pending_runtimes()

    # Runtime marqué failed car au moins 1 instance failed
    runtime_row = await fresh_db.fetchrow(
        "SELECT status FROM project_runtimes WHERE id = $1", runtime_id
    )
    assert runtime_row["status"] == "failed"

    pri_rows = await fresh_db.fetch(
        """
        SELECT provisioning_status, error_message
        FROM project_runtime_instances
        WHERE project_runtime_id = $1
        """,
        runtime_id,
    )
    failed = [r for r in pri_rows if r["provisioning_status"] == "failed"]
    assert len(failed) >= 1
    assert "undefined var" in failed[0]["error_message"].lower()


async def test_process_pending_ignores_saas_runtimes(
    fresh_db, mock_pending_saas_runtime
):
    """Les runtimes SaaS (user_id NOT NULL) ne sont PAS traités par ce worker."""
    from agflow.workers import provisioning_worker

    runtime_id = mock_pending_saas_runtime["runtime_id"]
    await provisioning_worker.process_pending_runtimes()

    # Status inchangé (toujours pending)
    row = await fresh_db.fetchrow(
        "SELECT status FROM project_runtimes WHERE id = $1", runtime_id
    )
    assert row["status"] == "pending"


async def test_process_pending_skips_deleted_runtimes(
    fresh_db, mock_pending_workflow_runtime
):
    """Un runtime avec deleted_at NOT NULL est ignoré."""
    from agflow.workers import provisioning_worker

    runtime_id = mock_pending_workflow_runtime["runtime_id"]
    await fresh_db.execute(
        "UPDATE project_runtimes SET deleted_at = now() WHERE id = $1",
        runtime_id,
    )
    await provisioning_worker.process_pending_runtimes()

    row = await fresh_db.fetchrow(
        "SELECT status FROM project_runtimes WHERE id = $1", runtime_id
    )
    assert row["status"] == "pending"  # inchangé
```

**Fixtures requises** dans `backend/tests/conftest.py` :
- `mock_pending_workflow_runtime` : runtime workflow (`user_id NULL`) + 2 instances avec `connection_params` Jinja valides.
- `mock_pending_workflow_runtime_with_bad_jinja` : pareil mais avec une var Jinja qui n'existe pas dans le contexte.
- `mock_pending_saas_runtime` : runtime SaaS (`user_id NOT NULL`).

### Step 2 — Verify fail

- [ ] `cd backend && uv run pytest tests/workers/test_provisioning_worker.py -v`
- [ ] Attendu : `ModuleNotFoundError: agflow.workers.provisioning_worker`.

### Step 3 — Écrire le worker

- [ ] Créer `backend/src/agflow/workers/provisioning_worker.py` :

```python
"""Worker provisioning workflow v5 — tranche 2.

Boucle asyncio dans le process FastAPI (lifespan). Poll les project_runtimes
workflow (user_id IS NULL) en status='pending', rend les connection_params
+ setup_steps de chaque instance via Jinja, et marque les statuts.

Si toutes les instances passent à 'ready' → runtime 'deployed'.
Si au moins une 'failed' → runtime 'failed'.
Si au moins une 'pending_setup' (et aucune failed) → runtime 'deployed' aussi
(le contrat v5 §3.4 mappe ça en 'partially_ready' côté DTO, géré par le mapper).
"""
from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_all
from agflow.services import project_runtime_instances_service as pri_service
from agflow.services.jinja_render import JinjaRenderError, render_jsonb_jinja

_log = structlog.get_logger(__name__)

_POLL_INTERVAL_SECONDS = 5.0


async def process_pending_runtimes() -> None:
    """Une passe : poll + traite tous les runtimes workflow pending."""
    rows = await fetch_all(
        """
        SELECT id, project_id
        FROM project_runtimes
        WHERE status = 'pending'
          AND user_id IS NULL
          AND deleted_at IS NULL
        ORDER BY created_at
        """
    )
    for r in rows:
        try:
            await _provision_runtime_instances(runtime_id=r["id"], project_id=r["project_id"])
        except Exception:
            _log.exception(
                "workflow.provisioning_worker.unexpected_error",
                runtime_id=str(r["id"]),
            )


async def _provision_runtime_instances(
    *, runtime_id: UUID, project_id: UUID
) -> None:
    """Pour chaque pri row du runtime : render Jinja, mark_status."""
    rows = await pri_service.list_by_runtime(project_runtime_id=runtime_id)

    context = _build_jinja_context(runtime_id=runtime_id, project_id=project_id)

    saw_failed = False
    saw_pending_setup = False

    for pri in rows:
        if pri["provisioning_status"] != "provisioning":
            continue  # déjà traité

        # Lire le template connection_params + setup_steps depuis instances (déjà JOIN dans list_by_runtime)
        template_row = await fetch_all(
            """
            SELECT connection_params, setup_steps
            FROM instances
            WHERE id = $1
            """,
            pri["instance_id"],
        )
        if not template_row:
            await pri_service.mark_failed(
                pri_id=pri["id"],
                error_message="template instance row missing",
            )
            saw_failed = True
            continue

        tpl = template_row[0]
        try:
            rendered_params = render_jsonb_jinja(
                tpl["connection_params"] or {}, context
            )
            rendered_steps = render_jsonb_jinja(
                tpl["setup_steps"] or [], context
            )
        except JinjaRenderError as exc:
            await pri_service.mark_failed(
                pri_id=pri["id"], error_message=f"undefined var: {exc}"
            )
            saw_failed = True
            continue

        # Détermine final status :
        # - 'pending_setup' si setup_steps non vide ET tous ont status != 'completed'
        # - 'ready' sinon
        final_status = "ready"
        if isinstance(rendered_steps, list) and rendered_steps:
            non_completed = [
                s for s in rendered_steps
                if isinstance(s, dict) and s.get("status") != "completed"
            ]
            if non_completed:
                final_status = "pending_setup"
                saw_pending_setup = True

        await pri_service.mark_status(
            pri_id=pri["id"],
            status=final_status,
            connection_params=rendered_params,
            setup_steps=rendered_steps if isinstance(rendered_steps, list) else [],
        )

    # Status global du runtime
    if saw_failed:
        final_runtime_status = "failed"
    else:
        final_runtime_status = "deployed"

    await execute(
        "UPDATE project_runtimes SET status = $1 WHERE id = $2",
        final_runtime_status,
        runtime_id,
    )
    _log.info(
        "workflow.runtime.provisioning_done",
        runtime_id=str(runtime_id),
        status=final_runtime_status,
        had_pending_setup=saw_pending_setup,
    )


def _build_jinja_context(
    *, runtime_id: UUID, project_id: UUID
) -> dict[str, Any]:
    """Variables disponibles au rendu Jinja.

    V1 minimal : juste les ids. Étendre selon les besoins (machine, network,
    secrets dérivés).
    """
    return {
        "runtime": {
            "id": str(runtime_id),
            "project_id": str(project_id),
            "short_id": str(runtime_id).split("-")[0],
        }
    }


async def provisioning_worker_loop() -> None:
    """Boucle infinie — invoquée par lifespan FastAPI via asyncio.create_task."""
    _log.info("workflow.provisioning_worker.started")
    while True:
        try:
            await process_pending_runtimes()
        except asyncio.CancelledError:
            _log.info("workflow.provisioning_worker.cancelled")
            raise
        except Exception:
            _log.exception("workflow.provisioning_worker.loop_error")
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)
```

### Step 4 — Re-lancer

- [ ] `cd backend && uv run pytest tests/workers/test_provisioning_worker.py -v`
- [ ] Attendu : **4 PASS**.

### Step 5 — Lint

- [ ] `cd backend && uv run ruff check src/agflow/workers/provisioning_worker.py tests/workers/test_provisioning_worker.py`

### Step 6 — Commit

```bash
git add backend/src/agflow/workers/provisioning_worker.py \
        backend/tests/workers/test_provisioning_worker.py
git commit -m "feat(workflow-t2): provisioning_worker (poll pending + Jinja + mark status)"
```

---

## Tâche 6 — Wire-up du worker dans `main.py`

**Files:**
- Modify: `backend/src/agflow/main.py`

### Step 1 — Identifier le pattern lifespan existant

- [ ] Lire `backend/src/agflow/main.py` autour de la fonction `lifespan` ou de l'app startup. Identifier comment les workers existants (`agent_reaper`, `docker_reconciler`, `session_idle_reaper`) sont démarrés.

### Step 2 — Ajouter le worker workflow

- [ ] Ajouter l'import en haut de `main.py` :

```python
from agflow.workers.provisioning_worker import provisioning_worker_loop
```

- [ ] Dans la fonction `lifespan` (ou équivalent), ajouter dans la liste des tasks créés au startup :

```python
provisioning_task = asyncio.create_task(provisioning_worker_loop())
```

- [ ] Dans la section shutdown du lifespan, ajouter :

```python
provisioning_task.cancel()
try:
    await provisioning_task
except asyncio.CancelledError:
    pass
```

**Note d'implémentation** : suivre exactement le pattern utilisé pour les workers existants — si le repo utilise une liste `workers = [task1, task2]` puis une boucle d'annulation, ajouter `provisioning_task` à cette liste plutôt que de dupliquer le pattern.

### Step 3 — Lancer pytest global pour vérifier le startup

- [ ] `cd backend && uv run pytest tests/ -v --co | head -20`
- [ ] Vérifier qu'il n'y a pas d'erreur d'import.

### Step 4 — Lint

- [ ] `cd backend && uv run ruff check src/agflow/main.py`

### Step 5 — Commit

```bash
git add backend/src/agflow/main.py
git commit -m "feat(workflow-t2): wire provisioning_worker_loop dans lifespan"
```

---

## Tâche 7 — Adapter le DTO `ResourceState` du contrat v5

**Files:**
- Modify: `backend/src/agflow/schemas/workflow.py`
- Modify: `backend/src/agflow/api/admin/workflow_runtimes.py`

### Step 1 — Étendre `ResourceState`

- [ ] Ouvrir `backend/src/agflow/schemas/workflow.py`, repérer la classe `ResourceState`.
- [ ] Ajouter les champs manquants pour conformité contrat v5 :

```python
class ResourceState(BaseModel):
    resource_id: UUID = Field(description="UUID v4 stable par runtime")
    type: str
    name: str
    status: str = Field(description="provisioning | ready | failed | pending_setup")
    connection_params: dict[str, Any] | None = None
    mcp_bindings: list[dict[str, Any]] = Field(default_factory=list)
    setup_steps: list[dict[str, Any]] = Field(default_factory=list)
    error_message: str | None = None
```

> **Note** : si `ResourceState` utilisait déjà `instance_id` comme nom de champ
> (héritage T1), remplacer par `resource_id`. Le client ag.flow consomme ce
> nom selon le contrat v5 §3.4.

### Step 2 — Adapter l'endpoint `GET /resources`

- [ ] Ouvrir `backend/src/agflow/api/admin/workflow_runtimes.py`. Adapter le mapping dans `get_runtime_resources` :

```python
@router.get(
    "/api/admin/project-runtimes/{runtime_id}/resources",
    response_model=RuntimeResourcesResponse,
)
async def get_runtime_resources(runtime_id: UUID) -> RuntimeResourcesResponse:
    runtime = await fetch_one(
        "SELECT status FROM project_runtimes WHERE id = $1 AND deleted_at IS NULL",
        runtime_id,
    )
    if runtime is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "runtime_not_found"},
        )

    rows = await wp.get_resources(runtime_id=runtime_id)
    resources = [
        ResourceState(
            resource_id=r["resource_id"],
            type=r["type"],
            name=r["name"],
            status=r["status"],
            connection_params=r.get("connection_params"),
            mcp_bindings=r.get("mcp_bindings") or [],
            setup_steps=r.get("setup_steps") or [],
            error_message=r.get("error_message"),
        )
        for r in rows
    ]
    return RuntimeResourcesResponse(
        runtime_id=runtime_id,
        status=_map_runtime_status_v5(runtime["status"], resources),
        resources=resources,
    )


def _map_runtime_status_v5(
    db_status: str, resources: list[ResourceState]
) -> str:
    """Mapping contrat v5 §3.4 :
    - 'provisioning' : DB pending OU au moins une resource encore provisioning
    - 'ready' : DB deployed ET toutes resources ready
    - 'partially_ready' : DB deployed ET au moins une resource pending_setup
    - 'failed' : DB failed OU au moins une resource failed
    """
    if db_status == "failed":
        return "failed"
    if any(r.status == "failed" for r in resources):
        return "failed"
    if db_status == "pending":
        return "provisioning"
    if any(r.status == "provisioning" for r in resources):
        return "provisioning"
    if any(r.status == "pending_setup" for r in resources):
        return "partially_ready"
    return "ready"
```

### Step 3 — Adapter / ajouter les tests existants

- [ ] Si `backend/tests/api/test_admin_workflow_runtimes.py` existe (T1), adapter les assertions pour le nouveau format de réponse (`resource_id` au lieu de `instance_id`, etc.).

### Step 4 — Re-lancer

- [ ] `cd backend && uv run pytest tests/api/test_admin_workflow_runtimes.py -v`

### Step 5 — Lint

- [ ] `cd backend && uv run ruff check src/agflow/schemas/workflow.py src/agflow/api/admin/workflow_runtimes.py`

### Step 6 — Commit

```bash
git add backend/src/agflow/schemas/workflow.py \
        backend/src/agflow/api/admin/workflow_runtimes.py \
        backend/tests/api/test_admin_workflow_runtimes.py
git commit -m "feat(workflow-t2): DTO ResourceState + mapping status v5 (provisioning/ready/partially_ready/failed)"
```

---

## Tâche 8 — Push origin/dev

- [ ] `git push origin dev`

---

## Tâche 9 — Validation E2E LXC fresh

### Step 1 — Lancer le test E2E complet

- [ ] `./scripts/run-test.sh`
- [ ] Attendu :
  - LXC fresh créé
  - Code déployé (commit le plus récent sur dev)
  - 8/8 assertions smoke
  - pytest complet (incluant les ~22 nouveaux tests T2)

### Step 2 — Smoke API manuel sur le LXC

- [ ] Récupérer l'IP du LXC + le mot de passe admin dans la sortie de `run-test.sh`.
- [ ] Vérifier le flow workflow complet :

```bash
# 1) Login admin
TOKEN=$(curl -sS -X POST "http://<IP>/api/admin/auth/login" \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@agflow.example.com","password":"<password>"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# 2) Lister les projets v5 (catalogue)
PROJECT_ID=$(curl -sS "http://<IP>/api/admin/projects/v5/list" \
  -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['project_id'])")

# 3) Provisionner un runtime
RUNTIME_ID=$(curl -sS -X POST "http://<IP>/api/admin/projects/$PROJECT_ID/runtimes" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['runtime_id'])")

# 4) Attendre 8s pour laisser le worker rendre Jinja
sleep 8

# 5) GET /resources : doit retourner status='ready' + connection_params rendus
curl -sS "http://<IP>/api/admin/project-runtimes/$RUNTIME_ID/resources" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
# Attendu :
#   - status: "ready" (ou "partially_ready" si setup_steps)
#   - resources[]: chaque resource a resource_id distinct, connection_params sans {{
```

### Step 3 — Cleanup LXC

- [ ] `ssh pve "pct stop <CTID> && pct destroy <CTID> --purge"`

### Step 4 — Mise à jour mémoire modules

- [ ] Mettre à jour `C:\Users\g.beard\.claude\projects\E--srcs-agflow-docker\memory\project_modules_status.md` : "Workflow Contracts" → "Tranche 2 livrée 2026-05-{jj}".

---

## Récapitulatif

**~9 commits livrés :**

1. `feat(workflow-t2): migration 002 project_runtime_instances + test de présence`
2. `feat(workflow-t2): project_runtime_instances_service (CRUD + bulk insert)`
3. `feat(workflow-t2): helper jinja_render (sandboxed + récursif jsonb)`
4. `refactor(workflow-t2): provision_runtime crée pri rows + get_resources lit nouvelle table`
5. `feat(workflow-t2): provisioning_worker (poll pending + Jinja + mark status)`
6. `feat(workflow-t2): wire provisioning_worker_loop dans lifespan`
7. `feat(workflow-t2): DTO ResourceState + mapping status v5 (provisioning/ready/partially_ready/failed)`

**~22 tests pytest** : 3 DB présence + 5 pri_service + 6 jinja_render + 4 provisioning_service + 4 provisioning_worker.

**Wall time estimé :** 4-5 jours.

**Hors scope explicite (différé tranche 2 bis / tranche 3+) :**
- Cleanup `instances` (retrait `provisioning_status`, `service_url`)
- Worker hook dispatcher HMAC (tranche 3)
- Consumer MOM `task.completed` (tranche 3)
- Endpoints `DELETE /hmac-keys/{id}` + `GET /tasks/{id}` (tranche 4)
- Mock-receiver dans `run-test.sh` (tranche 4)
