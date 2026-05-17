# Workflow Contracts — Tranche 1 (plan d'implémentation)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implémenter le squelette des 9 endpoints `/api/admin/*` du contrat workflow ag.flow ↔ agflow.docker (8 contrats v5 + 1 utilitaire `POST /hmac-keys`), wrappers thin sur les services M5 existants, sans worker provisioning ni hook dispatcher (différés tranche 2).

**Architecture:** Le schéma DB est **déjà en place** via `001_init.sql` consolidé (tables `tasks`, `hmac_keys`, `outbound_hooks` + colonnes ALTER sur `sessions`/`instances`/`agents_instances`). La tranche 1 livre uniquement la couche **services + endpoints + DTOs**. Authentification existante (`require_operator_or_m2m` avec scope `m2m:orchestrate`) déjà branchée. `POST /runtimes` est sync simulé (status passe immédiatement à "deployed" en interne, exposé comme "provisioning" → "ready" via mapping DTO). `POST /work` insère une `tasks` (status=pending) + MOM publish vers l'agent, sans hook outbound (worker dispatcher différé).

**Tech Stack:** Python 3.12 + FastAPI + asyncpg + Pydantic v2 + structlog + pytest + pytest-asyncio. Backend uniquement (pas de frontend en tranche 1).

**Spec de référence :** `docs/superpowers/specs/2026-05-17-workflow-contracts-tranche-1-design.md` (commit `d0b87dc`). **Note vs spec** : la spec décrit une migration 111 qui n'est plus nécessaire — `001_init.sql` consolidé contient déjà tous les ALTER et CREATE TABLE requis. Le plan ajuste en conséquence (T1 vérification de présence au lieu de création).

**Branche cible :** `dev`. Pas de feature branch.

**Mode pipeline allégé** (validé sur M6 Phase 2a, 2b, git-sync) : implementer subagent + spec compliance reviewer + code quality reviewer. Exécution continue.

**Note tests** :
- `pytest` certains tests d'intégration DB peuvent retourner DONE_WITH_CONCERNS sur dev Windows (LXC injoignable).
- Validation finale via `./scripts/run-test.sh` à T9.

---

## Structure des fichiers (vue d'ensemble)

### Backend (8 nouveaux + 2 modifs)

| Fichier | Responsabilité | Lignes |
|---|---|---|
| `backend/src/agflow/schemas/workflow.py` (nouveau) | DTOs Pydantic v2 conformes contrat v5 | ~180 |
| `backend/src/agflow/services/hmac_keys_service.py` (nouveau) | CRUD hmac_keys + chiffrement Harpocrate de `key_value_encrypted` | ~80 |
| `backend/src/agflow/services/tasks_service.py` (nouveau) | CRUD tasks + idempotence (session_id, agflow_correlation_id) | ~100 |
| `backend/src/agflow/services/workflow_provisioning_service.py` (nouveau) | `provision_runtime(project_id)` : INSERT runtime + copie resources + return runtime_id | ~120 |
| `backend/src/agflow/api/admin/hmac_keys.py` (nouveau) | Endpoint POST `/api/admin/hmac-keys` | ~70 |
| `backend/src/agflow/api/admin/workflow_runtimes.py` (nouveau) | Endpoints POST `/projects/{id}/runtimes` + GET `/project-runtimes/{id}/resources` | ~140 |
| `backend/src/agflow/api/admin/workflow_sessions.py` (nouveau) | Endpoints POST `/sessions` + POST `/sessions/{sid}/agents` + POST `/work` + DELETE `/sessions/{sid}` | ~220 |
| `backend/src/agflow/api/admin/projects.py` (modif) | Adapter DTO de `GET /projects` et `GET /projects/{id}` au contrat v5 (ajout `resources_summary`) | +40 |
| `backend/src/agflow/main.py` (modif) | `include_router` × 3 (workflow_runtimes, workflow_sessions, hmac_keys) | +6 |
| `backend/tests/db/test_workflow_tables_present.py` (nouveau) | Vérifie que tables + colonnes attendues sont présentes (sécurité) | ~80 |

### Tests (7 fichiers nouveaux)

| Fichier | Tests |
|---|---|
| `backend/tests/db/test_workflow_tables_present.py` | 4 : tables hmac_keys/tasks/outbound_hooks existent, sessions.{callback_url,callback_hmac_key_id,project_runtime_id}, agents_instances.mcp_bindings_injected, instances.{connection_params,mcp_bindings,setup_steps,provisioning_status} |
| `backend/tests/services/test_hmac_keys_service.py` | 3 : create encode+stocke, duplicate raise, get_by_key_id retourne secret déchiffré |
| `backend/tests/services/test_tasks_service.py` | 4 : create_session_work insère pending, conflit (session_id, agflow_correlation_id) retourne existant, get_by_id, list_for_session |
| `backend/tests/services/test_workflow_provisioning_service.py` | 3 : provision_runtime copie groups+instances, status final deployed, project inexistant raise |
| `backend/tests/api/test_admin_hmac_keys.py` | 2 : POST 201 + duplicate 409 |
| `backend/tests/api/test_admin_workflow_runtimes.py` | 3 : POST /runtimes (auth m2m + 202), GET /resources structure, 404 runtime inexistant |
| `backend/tests/api/test_admin_workflow_sessions.py` | 5 : POST /sessions avec callback+hmac, POST /agents fusion MCP, POST /work crée task + MOM publish, POST /work idempotent 409, DELETE force=true |

**Total : 24 tests pytest.**

---

## Tâche 1 — Test de présence des structures DB

**Files:**
- Create: `backend/tests/db/test_workflow_tables_present.py`

### Step 1 — Écrire le test

- [ ] Créer `backend/tests/db/test_workflow_tables_present.py` :

```python
"""Vérifie que les tables et colonnes du contrat workflow sont en place.

Le schéma a été livré via 001_init.sql consolidé (mai 2026). Ce test
fait office de garde-fou pour détecter une régression de structure
avant qu'elle ne casse les services en T2-T8.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def _column_exists(fresh_db, table: str, column: str) -> bool:
    row = await fresh_db.fetchrow(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = $1 AND column_name = $2
        """,
        table, column,
    )
    return row is not None


async def _table_exists(fresh_db, table: str) -> bool:
    row = await fresh_db.fetchrow(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_name = $1
        """,
        table,
    )
    return row is not None


async def test_workflow_tables_exist(fresh_db):
    """Tables nouvelles requises par le contrat workflow."""
    for t in ("hmac_keys", "tasks", "outbound_hooks"):
        assert await _table_exists(fresh_db, t), f"table manquante : {t}"


async def test_sessions_workflow_columns(fresh_db):
    """Sessions étendues : callback_url, callback_hmac_key_id, project_runtime_id."""
    for c in ("callback_url", "callback_hmac_key_id", "project_runtime_id"):
        assert await _column_exists(fresh_db, "sessions", c), (
            f"colonne sessions.{c} manquante"
        )


async def test_agents_instances_mcp_bindings_injected(fresh_db):
    assert await _column_exists(
        fresh_db, "agents_instances", "mcp_bindings_injected"
    )


async def test_instances_provisioning_columns(fresh_db):
    """Resources étendues : connection_params, mcp_bindings, setup_steps, provisioning_status."""
    for c in (
        "connection_params",
        "mcp_bindings",
        "setup_steps",
        "provisioning_status",
    ):
        assert await _column_exists(fresh_db, "instances", c), (
            f"colonne instances.{c} manquante"
        )
```

### Step 2 — Lancer le test

- [ ] Lancer : `cd backend && uv run pytest tests/db/test_workflow_tables_present.py -v`
- [ ] Attendu : **4 tests PASS** (DONE_WITH_CONCERNS acceptable si DB injoignable depuis Windows).

### Step 3 — Lint

- [ ] Lancer : `cd backend && uv run ruff check tests/db/test_workflow_tables_present.py`

### Step 4 — Commit

```bash
git add backend/tests/db/test_workflow_tables_present.py
git commit -m "test(workflow): garde-fou présence tables/colonnes workflow contracts"
```

---

## Tâche 2 — DTOs Pydantic `schemas/workflow.py`

**Files:**
- Create: `backend/src/agflow/schemas/workflow.py`

Pas de test dédié — les DTOs sont validés via les tests des endpoints en T6-T8.

### Step 1 — Créer le fichier

- [ ] Créer `backend/src/agflow/schemas/workflow.py` :

```python
"""DTOs Pydantic v2 conformes au contrat workflow v5
(cf. docs/contracts/docker-orchestration-flow.md).
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ── Catalogue projets (#1, #2) ─────────────────────────────────────


class ResourceSummary(BaseModel):
    type: str
    label: str


class ProjectSummaryV5(BaseModel):
    project_id: UUID
    name: str
    description: str
    resources_summary: list[ResourceSummary]


class ResourceDetail(BaseModel):
    type: str
    label: str
    catalog_id: str


class ProjectDetailV5(BaseModel):
    project_id: UUID
    name: str
    description: str
    resources: list[ResourceDetail]


# ── Runtimes (#3, #4) ──────────────────────────────────────────────


class RuntimeProvisionResponse(BaseModel):
    runtime_id: UUID
    status: str = Field(description='Au moment du début : "provisioning"')


class ResourceState(BaseModel):
    instance_id: UUID
    type: str
    name: str
    status: str = Field(description="provisioning | ready | failed | pending_setup")
    connection_params: dict[str, Any] | None = None


class RuntimeResourcesResponse(BaseModel):
    runtime_id: UUID
    status: str = Field(description='provisioning | ready | failed (mapped from pending|deployed|failed)')
    resources: list[ResourceState]


# ── Sessions (#5, #6, #7, #8) ──────────────────────────────────────


class SessionCreateRequest(BaseModel):
    api_key_id: UUID
    name: str | None = None
    duration_seconds: int = Field(ge=60, le=86_400 * 30)
    project_runtime_id: UUID | None = None
    callback_url: str | None = None
    callback_hmac_key_id: str | None = Field(default=None, max_length=64)


class SessionCreateResponse(BaseModel):
    session_id: UUID
    expires_at: str


class AgentCreateRequest(BaseModel):
    agent_id: str = Field(min_length=1, max_length=128)
    labels: dict[str, Any] = Field(default_factory=dict)
    mission: str | None = None
    count: int = Field(default=1, ge=1, le=10)


class AgentCreateResponse(BaseModel):
    agent_instance_ids: list[UUID]


class WorkRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    agflow_correlation_id: UUID = Field(alias="_agflow_correlation_id")
    instruction: dict[str, Any]


class WorkResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    task_id: UUID
    agflow_correlation_id: UUID = Field(alias="_agflow_correlation_id")


# ── HMAC keys (#9) ─────────────────────────────────────────────────


class HmacKeyCreateRequest(BaseModel):
    key_id: str = Field(min_length=1, max_length=64)
    secret_hex: str = Field(min_length=32, max_length=128)
    description: str = ""


class HmacKeyCreateResponse(BaseModel):
    key_id: str
    description: str
    created_at: str
```

### Step 2 — TypeScript-équivalent (mypy/ruff)

- [ ] Lancer : `cd backend && uv run ruff check src/agflow/schemas/workflow.py`
- [ ] Attendu : All checks passed.

### Step 3 — Commit

```bash
git add backend/src/agflow/schemas/workflow.py
git commit -m "feat(workflow-schemas): DTOs Pydantic v2 conformes contrat v5"
```

---

## Tâche 3 — `services/hmac_keys_service.py`

**Files:**
- Create: `backend/src/agflow/services/hmac_keys_service.py`
- Test: `backend/tests/services/test_hmac_keys_service.py`

**Note** : la colonne s'appelle `key_value_encrypted bytea` (chiffré). Le service fait l'encrypt/decrypt à la volée. Le `harpocrate_dek` (config) est utilisé pour le chiffrement symétrique (Fernet). **Si** un autre service du repo utilise déjà cette clé, réutiliser. Sinon utiliser `cryptography.fernet.Fernet` avec `settings.harpocrate_dek` (déjà disponible).

### Step 1 — Écrire le test (failing)

- [ ] Créer `backend/tests/services/test_hmac_keys_service.py` :

```python
"""Tests de hmac_keys_service."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_create_inserts_and_encrypts(fresh_db):
    from agflow.services import hmac_keys_service

    secret = "0123456789abcdef" * 4  # 64 hex
    await hmac_keys_service.create(
        key_id="test-key-1",
        secret_hex=secret,
        description="test key",
    )
    row = await fresh_db.fetchrow(
        "SELECT key_id, key_value_encrypted, description FROM hmac_keys WHERE key_id = $1",
        "test-key-1",
    )
    assert row is not None
    assert row["description"] == "test key"
    # encrypted blob != cleartext
    assert bytes(row["key_value_encrypted"]) != secret.encode()


async def test_create_duplicate_raises(fresh_db):
    from agflow.services import hmac_keys_service

    secret = "0123456789abcdef" * 4
    await hmac_keys_service.create(key_id="dup-key", secret_hex=secret, description="")
    with pytest.raises(hmac_keys_service.DuplicateHmacKeyError):
        await hmac_keys_service.create(
            key_id="dup-key", secret_hex=secret, description=""
        )


async def test_get_by_key_id_returns_decrypted(fresh_db):
    from agflow.services import hmac_keys_service

    secret = "0123456789abcdef" * 4
    await hmac_keys_service.create(
        key_id="readback", secret_hex=secret, description=""
    )
    got = await hmac_keys_service.get_by_key_id("readback")
    assert got is not None
    assert got["secret_hex"] == secret
    assert got["key_id"] == "readback"
```

### Step 2 — Lancer test (verify fail)

- [ ] Lancer : `cd backend && uv run pytest tests/services/test_hmac_keys_service.py -v`
- [ ] Attendu : `ModuleNotFoundError: agflow.services.hmac_keys_service`.

### Step 3 — Écrire le service

- [ ] Créer `backend/src/agflow/services/hmac_keys_service.py` :

```python
"""CRUD de la table hmac_keys (callbacks HMAC pour workflows).

Stockage : secret_hex chiffré au repos via Fernet (clé = settings.harpocrate_dek).
"""
from __future__ import annotations

from base64 import urlsafe_b64encode
from hashlib import sha256

import asyncpg
import structlog
from cryptography.fernet import Fernet, InvalidToken

from agflow.config import get_settings
from agflow.db.pool import execute, fetch_one

_log = structlog.get_logger(__name__)


class DuplicateHmacKeyError(Exception):
    pass


class HmacKeyNotFoundError(Exception):
    pass


def _fernet() -> Fernet:
    """Dérive une clé Fernet à partir de settings.harpocrate_dek."""
    dek = get_settings().harpocrate_dek
    if not dek:
        raise RuntimeError(
            "harpocrate_dek non configurée — hmac_keys nécessite cette clé"
        )
    derived = urlsafe_b64encode(sha256(dek.encode()).digest())
    return Fernet(derived)


async def create(
    *, key_id: str, secret_hex: str, description: str = ""
) -> None:
    fernet = _fernet()
    encrypted = fernet.encrypt(secret_hex.encode())
    try:
        await execute(
            """
            INSERT INTO hmac_keys (key_id, key_value_encrypted, description)
            VALUES ($1, $2, $3)
            """,
            key_id,
            encrypted,
            description,
        )
    except asyncpg.UniqueViolationError as exc:
        raise DuplicateHmacKeyError(f"key_id '{key_id}' already exists") from exc
    _log.info("workflow.hmac_key.created", key_id=key_id)


async def get_by_key_id(key_id: str) -> dict | None:
    row = await fetch_one(
        """
        SELECT key_id, key_value_encrypted, description, created_at
        FROM hmac_keys
        WHERE key_id = $1
        """,
        key_id,
    )
    if row is None:
        return None
    fernet = _fernet()
    try:
        secret_hex = fernet.decrypt(bytes(row["key_value_encrypted"])).decode()
    except InvalidToken as exc:
        _log.error("workflow.hmac_key.decrypt_failed", key_id=key_id)
        raise RuntimeError(f"hmac key '{key_id}' decryption failed") from exc
    return {
        "key_id": row["key_id"],
        "secret_hex": secret_hex,
        "description": row["description"],
        "created_at": row["created_at"],
    }


async def exists(key_id: str) -> bool:
    row = await fetch_one(
        "SELECT 1 FROM hmac_keys WHERE key_id = $1 AND rotated_at IS NULL",
        key_id,
    )
    return row is not None
```

### Step 4 — Re-lancer test

- [ ] Lancer : `cd backend && uv run pytest tests/services/test_hmac_keys_service.py -v`
- [ ] Attendu : **3 tests PASS** (DONE_WITH_CONCERNS acceptable si DB injoignable).

### Step 5 — Lint

- [ ] Lancer : `cd backend && uv run ruff check src/agflow/services/hmac_keys_service.py tests/services/test_hmac_keys_service.py`

### Step 6 — Commit

```bash
git add backend/src/agflow/services/hmac_keys_service.py \
         backend/tests/services/test_hmac_keys_service.py
git commit -m "feat(workflow-hmac): hmac_keys_service (CRUD + Fernet encrypt via harpocrate_dek)"
```

---

## Tâche 4 — `services/tasks_service.py`

**Files:**
- Create: `backend/src/agflow/services/tasks_service.py`
- Test: `backend/tests/services/test_tasks_service.py`

**Note** : la table `tasks` n'a pas de UNIQUE constraint sur `(session_id, agflow_correlation_id)` dans `001_init.sql`. L'idempotence est donc gérée **applicativement** : SELECT avant INSERT.

### Step 1 — Écrire le test

```python
"""Tests de tasks_service."""
from __future__ import annotations

from uuid import uuid4

import pytest

pytestmark = pytest.mark.asyncio


async def test_create_session_work_inserts_pending(fresh_db, mock_session_and_agent):
    """mock_session_and_agent : fixture qui crée une session + agent_instance valides."""
    from agflow.services import tasks_service

    sid, aid = mock_session_and_agent
    cid = uuid4()
    task = await tasks_service.create_session_work(
        session_id=sid,
        agent_instance_id=aid,
        agflow_correlation_id=cid,
        instruction={"text": "do something"},
    )
    assert task["status"] == "pending"
    assert task["kind"] == "session_work"
    assert task["agflow_correlation_id"] == cid


async def test_create_session_work_idempotent(fresh_db, mock_session_and_agent):
    from agflow.services import tasks_service

    sid, aid = mock_session_and_agent
    cid = uuid4()
    first = await tasks_service.create_session_work(
        session_id=sid,
        agent_instance_id=aid,
        agflow_correlation_id=cid,
        instruction={"text": "first"},
    )
    second = await tasks_service.create_session_work(
        session_id=sid,
        agent_instance_id=aid,
        agflow_correlation_id=cid,
        instruction={"text": "second"},  # ignored
    )
    assert first["task_id"] == second["task_id"]
    # was_existing flag indique le hit idempotence
    assert second["was_existing"] is True


async def test_get_by_id_returns_task(fresh_db, mock_session_and_agent):
    from agflow.services import tasks_service

    sid, aid = mock_session_and_agent
    cid = uuid4()
    created = await tasks_service.create_session_work(
        session_id=sid,
        agent_instance_id=aid,
        agflow_correlation_id=cid,
        instruction={"x": 1},
    )
    got = await tasks_service.get_by_id(created["task_id"])
    assert got is not None
    assert got["task_id"] == created["task_id"]


async def test_get_by_id_unknown_returns_none(fresh_db):
    from agflow.services import tasks_service

    got = await tasks_service.get_by_id(uuid4())
    assert got is None
```

**Note fixture** : si `mock_session_and_agent` n'existe pas, l'implementer doit l'ajouter au `conftest.py` voisin pour créer une vraie session + agent via INSERT direct (pas via les services qui pourraient avoir des side-effects).

### Step 2 — Verify fail

- [ ] Lancer : `cd backend && uv run pytest tests/services/test_tasks_service.py -v`
- [ ] Attendu : `ModuleNotFoundError: agflow.services.tasks_service`.

### Step 3 — Écrire le service

- [ ] Créer `backend/src/agflow/services/tasks_service.py` :

```python
"""CRUD de la table tasks (suivi des opérations workflow async)."""
from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

import structlog

from agflow.db.pool import fetch_one

_log = structlog.get_logger(__name__)


async def create_session_work(
    *,
    session_id: UUID,
    agent_instance_id: UUID,
    agflow_correlation_id: UUID,
    instruction: dict[str, Any],
) -> dict:
    """Crée une tâche kind='session_work' avec idempotence applicative.

    Si une tâche avec ce (session_id, agflow_correlation_id) existe déjà,
    on la retourne avec `was_existing=True` sans rien insérer (instruction
    ignorée).
    """
    existing = await fetch_one(
        """
        SELECT id, kind, status, agflow_correlation_id
        FROM tasks
        WHERE session_id = $1
          AND agflow_correlation_id = $2
          AND kind = 'session_work'
        """,
        session_id,
        agflow_correlation_id,
    )
    if existing:
        return {
            "task_id": existing["id"],
            "kind": existing["kind"],
            "status": existing["status"],
            "agflow_correlation_id": existing["agflow_correlation_id"],
            "was_existing": True,
        }

    row = await fetch_one(
        """
        INSERT INTO tasks (
            id, kind, session_id, agent_instance_id,
            agflow_correlation_id, status, result
        )
        VALUES ($1, 'session_work', $2, $3, $4, 'pending', $5::jsonb)
        RETURNING id, kind, status, agflow_correlation_id
        """,
        uuid4(),
        session_id,
        agent_instance_id,
        agflow_correlation_id,
        json.dumps({"instruction": instruction}),
    )
    _log.info(
        "workflow.task.created",
        task_id=str(row["id"]),
        session_id=str(session_id),
        agent_instance_id=str(agent_instance_id),
        agflow_correlation_id=str(agflow_correlation_id),
    )
    return {
        "task_id": row["id"],
        "kind": row["kind"],
        "status": row["status"],
        "agflow_correlation_id": row["agflow_correlation_id"],
        "was_existing": False,
    }


async def get_by_id(task_id: UUID) -> dict | None:
    row = await fetch_one(
        """
        SELECT id, kind, status, session_id, agent_instance_id,
               agflow_correlation_id, result, error,
               created_at, completed_at
        FROM tasks
        WHERE id = $1
        """,
        task_id,
    )
    if row is None:
        return None
    return {
        "task_id": row["id"],
        "kind": row["kind"],
        "status": row["status"],
        "session_id": row["session_id"],
        "agent_instance_id": row["agent_instance_id"],
        "agflow_correlation_id": row["agflow_correlation_id"],
        "result": row["result"],
        "error": row["error"],
        "created_at": row["created_at"],
        "completed_at": row["completed_at"],
    }
```

### Step 4 — Re-lancer

- [ ] Lancer : `cd backend && uv run pytest tests/services/test_tasks_service.py -v`
- [ ] Attendu : **4 tests PASS**.

### Step 5 — Lint

- [ ] Lancer : `cd backend && uv run ruff check src/agflow/services/tasks_service.py tests/services/test_tasks_service.py`

### Step 6 — Commit

```bash
git add backend/src/agflow/services/tasks_service.py \
         backend/tests/services/test_tasks_service.py
git commit -m "feat(workflow-tasks): tasks_service (create_session_work idempotent + get)"
```

---

## Tâche 5 — `services/workflow_provisioning_service.py`

**Files:**
- Create: `backend/src/agflow/services/workflow_provisioning_service.py`
- Test: `backend/tests/services/test_workflow_provisioning_service.py`

**Comportement** : `provision_runtime(project_id)` insère une `project_runtimes` row (status='pending'), pour chaque `instances` du projet (via `groups`) copie une ligne dans `instances` avec `runtime_id` (note : `instances` est lié à `groups`, pas à `runtime` — l'architecture exacte dépendra de comment Phase 1 SaaS Runtimes a structuré ça). Pour la tranche 1 : on **n'ajoute pas de nouvelle ligne instance** par runtime, on lit les `instances` existantes du projet (filtrées par groups du projet) et on simule l'état "ready" sans copier. À cadrer en début d'impl.

### Step 1 — Inspecter le pattern Phase 1 SaaS

- [ ] Lancer : `grep -n "project_runtimes\|provision" backend/src/agflow/services/*.py | head -20`
- [ ] Lire `backend/src/agflow/services/product_instances_service.py` et le service Phase 1 SaaS qui crée les runtimes (probablement dans `runtimes_service.py` ou similaire).
- [ ] Identifier comment Phase 1 lie un runtime à ses resources (`product_instances` rows distinctes par runtime, OU partage via groups). Adapter l'approche tranche 1 en conséquence.

### Step 2 — Écrire le test

- [ ] Créer `backend/tests/services/test_workflow_provisioning_service.py` :

```python
"""Tests de workflow_provisioning_service."""
from __future__ import annotations

from uuid import uuid4

import pytest

pytestmark = pytest.mark.asyncio


async def test_provision_runtime_inserts_row(fresh_db, mock_project_with_resources):
    """mock_project_with_resources : fixture qui crée un projet avec ≥1 group+instance."""
    from agflow.services import workflow_provisioning_service as wp

    project_id = mock_project_with_resources["project_id"]
    runtime_id = await wp.provision_runtime(project_id=project_id)

    row = await fresh_db.fetchrow(
        "SELECT status FROM project_runtimes WHERE id = $1",
        runtime_id,
    )
    assert row is not None
    # status final = deployed (sync simulé)
    assert row["status"] == "deployed"


async def test_provision_runtime_unknown_project_raises(fresh_db):
    from agflow.services import workflow_provisioning_service as wp

    with pytest.raises(wp.ProjectNotFoundError):
        await wp.provision_runtime(project_id=uuid4())


async def test_provision_runtime_copies_resources_summary(
    fresh_db, mock_project_with_resources
):
    """Le runtime expose les resources du projet via get_resources()."""
    from agflow.services import workflow_provisioning_service as wp

    project_id = mock_project_with_resources["project_id"]
    expected_count = mock_project_with_resources["resources_count"]
    runtime_id = await wp.provision_runtime(project_id=project_id)

    resources = await wp.get_resources(runtime_id=runtime_id)
    assert len(resources) == expected_count
```

### Step 3 — Verify fail

- [ ] Lancer : `cd backend && uv run pytest tests/services/test_workflow_provisioning_service.py -v`

### Step 4 — Écrire le service

- [ ] Créer `backend/src/agflow/services/workflow_provisioning_service.py` :

```python
"""Provisioning d'un project_runtime selon le contrat workflow v5.

Tranche 1 : sync simulé. INSERT project_runtimes + UPDATE status='deployed'
immédiatement. Pas de worker, pas de templating Jinja des connection_params.
"""
from __future__ import annotations

from uuid import UUID

import asyncpg
import structlog

from agflow.db.pool import execute, fetch_all, fetch_one

_log = structlog.get_logger(__name__)


class ProjectNotFoundError(Exception):
    pass


async def provision_runtime(*, project_id: UUID) -> UUID:
    """Crée un project_runtime et marque status='deployed' (sync simulé).

    Retourne le runtime_id.
    """
    project = await fetch_one("SELECT id FROM projects WHERE id = $1", project_id)
    if project is None:
        raise ProjectNotFoundError(f"project {project_id} not found")

    try:
        row = await fetch_one(
            """
            INSERT INTO project_runtimes (project_id, status, user_id)
            VALUES ($1, 'pending', NULL)
            RETURNING id
            """,
            project_id,
        )
    except asyncpg.PostgresError as exc:
        _log.exception("workflow.runtime.insert_failed", project_id=str(project_id))
        raise

    runtime_id: UUID = row["id"]

    # Tranche 1 : sync simulé — pas de worker, status passe immédiatement à deployed.
    await execute(
        "UPDATE project_runtimes SET status = 'deployed' WHERE id = $1",
        runtime_id,
    )

    _log.info(
        "workflow.runtime.provisioned",
        runtime_id=str(runtime_id),
        project_id=str(project_id),
    )
    return runtime_id


async def get_resources(*, runtime_id: UUID) -> list[dict]:
    """Liste les resources (instances) du runtime via le projet.

    Tranche 1 : on récupère les instances du projet (toutes groups confondus).
    En tranche 2, on copiera/cloncopiera chaque resource par runtime.
    """
    # On retrouve le project_id du runtime puis on liste ses instances via groups.
    runtime = await fetch_one(
        "SELECT project_id FROM project_runtimes WHERE id = $1",
        runtime_id,
    )
    if runtime is None:
        return []

    rows = await fetch_all(
        """
        SELECT i.id AS instance_id, i.catalog_id AS type,
               i.instance_name AS name, i.provisioning_status AS status,
               i.connection_params
        FROM instances i
        JOIN groups g ON g.id = i.group_id
        WHERE g.project_id = $1
        ORDER BY i.created_at
        """,
        runtime["project_id"],
    )
    return [dict(r) for r in rows]
```

### Step 5 — Re-lancer

- [ ] Lancer : `cd backend && uv run pytest tests/services/test_workflow_provisioning_service.py -v`
- [ ] Attendu : **3 tests PASS**.

### Step 6 — Lint

- [ ] Lancer : `cd backend && uv run ruff check src/agflow/services/workflow_provisioning_service.py tests/services/test_workflow_provisioning_service.py`

### Step 7 — Commit

```bash
git add backend/src/agflow/services/workflow_provisioning_service.py \
         backend/tests/services/test_workflow_provisioning_service.py
git commit -m "feat(workflow-provisioning): provision_runtime + get_resources (sync simulé)"
```

---

## Tâche 6 — Endpoint `POST /api/admin/hmac-keys`

**Files:**
- Create: `backend/src/agflow/api/admin/hmac_keys.py`
- Test: `backend/tests/api/test_admin_hmac_keys.py`

### Step 1 — Écrire le test

- [ ] Créer `backend/tests/api/test_admin_hmac_keys.py` :

```python
"""Tests de POST /api/admin/hmac-keys."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agflow.auth.jwt import encode_token


@pytest.fixture
def client():
    from agflow.main import app
    return TestClient(app)


def _admin_header() -> dict[str, str]:
    return {"Authorization": f"Bearer {encode_token('admin@test.local')}"}


def test_post_hmac_key_returns_201(client, fresh_db):
    response = client.post(
        "/api/admin/hmac-keys",
        json={
            "key_id": "test-k1",
            "secret_hex": "0123456789abcdef" * 4,
            "description": "test",
        },
        headers=_admin_header(),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["key_id"] == "test-k1"
    assert body["description"] == "test"


def test_post_hmac_key_duplicate_returns_409(client, fresh_db):
    payload = {
        "key_id": "dup-k1",
        "secret_hex": "0123456789abcdef" * 4,
        "description": "",
    }
    r1 = client.post("/api/admin/hmac-keys", json=payload, headers=_admin_header())
    assert r1.status_code == 201
    r2 = client.post("/api/admin/hmac-keys", json=payload, headers=_admin_header())
    assert r2.status_code == 409
```

### Step 2 — Verify fail

- [ ] Lancer : `cd backend && uv run pytest tests/api/test_admin_hmac_keys.py -v`
- [ ] Attendu : `ModuleNotFoundError` (le router n'est pas branché) OU 404 (route inconnue).

### Step 3 — Écrire le router

- [ ] Créer `backend/src/agflow/api/admin/hmac_keys.py` :

```python
"""Endpoint POST /api/admin/hmac-keys (gestion des clés HMAC du callback workflow)."""
from __future__ import annotations

from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, status

from agflow.auth.dependencies import require_operator_or_m2m
from agflow.schemas.workflow import HmacKeyCreateRequest, HmacKeyCreateResponse
from agflow.services import hmac_keys_service

_log = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/admin/hmac-keys",
    tags=["admin-workflow"],
    dependencies=[Depends(require_operator_or_m2m)],
)


@router.post(
    "",
    response_model=HmacKeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_hmac_key(payload: HmacKeyCreateRequest) -> HmacKeyCreateResponse:
    try:
        await hmac_keys_service.create(
            key_id=payload.key_id,
            secret_hex=payload.secret_hex,
            description=payload.description,
        )
    except hmac_keys_service.DuplicateHmacKeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "key_id_already_exists", "message": str(exc)},
        ) from exc

    return HmacKeyCreateResponse(
        key_id=payload.key_id,
        description=payload.description,
        created_at=datetime.now(UTC).isoformat(),
    )
```

### Step 4 — Brancher dans main.py

- [ ] Lancer : `grep -n "include_router\|admin_supervision_router" backend/src/agflow/main.py | head -5`
- [ ] Ajouter l'import à côté des autres :

```python
from agflow.api.admin.hmac_keys import router as admin_hmac_keys_router
```

- [ ] Ajouter l'inclusion :

```python
app.include_router(admin_hmac_keys_router)
```

### Step 5 — Re-lancer

- [ ] Lancer : `cd backend && uv run pytest tests/api/test_admin_hmac_keys.py -v`
- [ ] Attendu : **2 PASS**.

### Step 6 — Lint

- [ ] Lancer : `cd backend && uv run ruff check src/agflow/api/admin/hmac_keys.py src/agflow/main.py tests/api/test_admin_hmac_keys.py`

### Step 7 — Commit

```bash
git add backend/src/agflow/api/admin/hmac_keys.py \
         backend/src/agflow/main.py \
         backend/tests/api/test_admin_hmac_keys.py
git commit -m "feat(workflow-api): POST /api/admin/hmac-keys"
```

---

## Tâche 7 — Endpoints `/api/admin/projects/{id}/runtimes` (POST) + `/project-runtimes/{id}/resources` (GET)

**Files:**
- Create: `backend/src/agflow/api/admin/workflow_runtimes.py`
- Modify: `backend/src/agflow/main.py`
- Test: `backend/tests/api/test_admin_workflow_runtimes.py`

### Step 1 — Écrire le test

- [ ] Créer `backend/tests/api/test_admin_workflow_runtimes.py` :

```python
"""Tests des endpoints workflow runtimes."""
from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from agflow.auth.jwt import encode_token


@pytest.fixture
def client():
    from agflow.main import app
    return TestClient(app)


def _admin_header() -> dict[str, str]:
    return {"Authorization": f"Bearer {encode_token('admin@test.local')}"}


def test_post_runtime_returns_202_and_runtime_id(
    client, fresh_db, mock_project_with_resources
):
    project_id = mock_project_with_resources["project_id"]
    response = client.post(
        f"/api/admin/projects/{project_id}/runtimes",
        json={},
        headers=_admin_header(),
    )
    assert response.status_code == 202
    body = response.json()
    assert "runtime_id" in body
    # contrat v5 : status="provisioning" au moment du début
    assert body["status"] == "provisioning"


def test_post_runtime_unknown_project_returns_404(client, fresh_db):
    response = client.post(
        f"/api/admin/projects/{uuid4()}/runtimes",
        json={},
        headers=_admin_header(),
    )
    assert response.status_code == 404


def test_get_runtime_resources_returns_list(
    client, fresh_db, mock_project_with_resources
):
    project_id = mock_project_with_resources["project_id"]
    # Create runtime
    r1 = client.post(
        f"/api/admin/projects/{project_id}/runtimes",
        json={},
        headers=_admin_header(),
    )
    runtime_id = r1.json()["runtime_id"]
    # Get resources
    r2 = client.get(
        f"/api/admin/project-runtimes/{runtime_id}/resources",
        headers=_admin_header(),
    )
    assert r2.status_code == 200
    body = r2.json()
    assert body["runtime_id"] == runtime_id
    assert isinstance(body["resources"], list)
```

### Step 2 — Verify fail

- [ ] Lancer : `cd backend && uv run pytest tests/api/test_admin_workflow_runtimes.py -v`

### Step 3 — Écrire le router

- [ ] Créer `backend/src/agflow/api/admin/workflow_runtimes.py` :

```python
"""Endpoints workflow contracts v5 — runtimes.

- POST /api/admin/projects/{project_id}/runtimes
- GET  /api/admin/project-runtimes/{runtime_id}/resources
"""
from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, status

from agflow.auth.dependencies import require_operator_or_m2m
from agflow.db.pool import fetch_one
from agflow.schemas.workflow import (
    ResourceState,
    RuntimeProvisionResponse,
    RuntimeResourcesResponse,
)
from agflow.services import workflow_provisioning_service as wp

_log = structlog.get_logger(__name__)

router = APIRouter(
    tags=["admin-workflow"],
    dependencies=[Depends(require_operator_or_m2m)],
)


def _map_status(db_status: str) -> str:
    """Map status DB (pending|deployed|failed) vers contrat v5 (provisioning|ready|failed)."""
    return {
        "pending": "provisioning",
        "deployed": "ready",
        "failed": "failed",
    }.get(db_status, db_status)


@router.post(
    "/api/admin/projects/{project_id}/runtimes",
    response_model=RuntimeProvisionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def post_runtime(project_id: UUID) -> RuntimeProvisionResponse:
    try:
        runtime_id = await wp.provision_runtime(project_id=project_id)
    except wp.ProjectNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "project_not_found", "message": str(exc)},
        ) from exc

    # Contrat v5 : retourne "provisioning" même si en DB c'est déjà 'deployed' (sync simulé).
    return RuntimeProvisionResponse(runtime_id=runtime_id, status="provisioning")


@router.get(
    "/api/admin/project-runtimes/{runtime_id}/resources",
    response_model=RuntimeResourcesResponse,
)
async def get_runtime_resources(runtime_id: UUID) -> RuntimeResourcesResponse:
    runtime = await fetch_one(
        "SELECT status FROM project_runtimes WHERE id = $1",
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
            instance_id=r["instance_id"],
            type=r["type"],
            name=r["name"],
            status=r["status"],
            connection_params=r.get("connection_params"),
        )
        for r in rows
    ]
    return RuntimeResourcesResponse(
        runtime_id=runtime_id,
        status=_map_status(runtime["status"]),
        resources=resources,
    )
```

### Step 4 — Brancher dans main.py

- [ ] Ajouter l'import + `include_router`. Suivre le pattern de T6.

### Step 5 — Re-lancer

- [ ] Lancer : `cd backend && uv run pytest tests/api/test_admin_workflow_runtimes.py -v`
- [ ] Attendu : **3 PASS**.

### Step 6 — Lint

- [ ] Lancer : `cd backend && uv run ruff check src/agflow/api/admin/workflow_runtimes.py src/agflow/main.py tests/api/test_admin_workflow_runtimes.py`

### Step 7 — Commit

```bash
git add backend/src/agflow/api/admin/workflow_runtimes.py \
         backend/src/agflow/main.py \
         backend/tests/api/test_admin_workflow_runtimes.py
git commit -m "feat(workflow-api): POST /projects/{id}/runtimes + GET /project-runtimes/{id}/resources"
```

---

## Tâche 8 — Endpoints workflow sessions/agents/work/delete

**Files:**
- Create: `backend/src/agflow/api/admin/workflow_sessions.py`
- Modify: `backend/src/agflow/main.py`
- Test: `backend/tests/api/test_admin_workflow_sessions.py`

### Step 1 — Écrire le test (couvre 5 scénarios)

- [ ] Créer `backend/tests/api/test_admin_workflow_sessions.py` :

```python
"""Tests des endpoints workflow sessions/agents/work/delete."""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from agflow.auth.jwt import encode_token


@pytest.fixture
def client():
    from agflow.main import app
    return TestClient(app)


def _admin_header() -> dict[str, str]:
    return {"Authorization": f"Bearer {encode_token('admin@test.local')}"}


def test_post_session_with_callback_and_hmac_key(
    client, fresh_db, mock_api_key, mock_hmac_key
):
    response = client.post(
        "/api/admin/sessions",
        json={
            "api_key_id": str(mock_api_key),
            "duration_seconds": 3600,
            "callback_url": "https://ag.flow/hooks/abc",
            "callback_hmac_key_id": mock_hmac_key,
        },
        headers=_admin_header(),
    )
    assert response.status_code == 201
    body = response.json()
    assert "session_id" in body
    # Vérifier en DB
    row = client.app.state  # placeholder — utiliser fresh_db cur


def test_post_session_with_unknown_hmac_key_returns_422(
    client, fresh_db, mock_api_key
):
    response = client.post(
        "/api/admin/sessions",
        json={
            "api_key_id": str(mock_api_key),
            "duration_seconds": 3600,
            "callback_url": "https://ag.flow/hooks/abc",
            "callback_hmac_key_id": "nonexistent",
        },
        headers=_admin_header(),
    )
    assert response.status_code == 422


def test_post_agents_with_session_linked_to_runtime_injects_mcp(
    client, fresh_db, mock_session_with_runtime
):
    """Fusion MCP : si session.project_runtime_id, agrège mcp_bindings."""
    sid = mock_session_with_runtime["session_id"]
    response = client.post(
        f"/api/admin/sessions/{sid}/agents",
        json={"agent_id": "claude-code-r1", "count": 1},
        headers=_admin_header(),
    )
    assert response.status_code == 201
    body = response.json()
    assert len(body["agent_instance_ids"]) == 1


def test_post_work_creates_task_pending_and_idempotent(
    client, fresh_db, mock_session_and_agent
):
    """POST /work crée la tâche, deuxième POST avec même correlation_id renvoie 409 + même task_id."""
    sid, aid = mock_session_and_agent
    cid = str(uuid4())
    r1 = client.post(
        f"/api/admin/sessions/{sid}/agents/{aid}/work",
        json={
            "_agflow_correlation_id": cid,
            "instruction": {"text": "do it"},
        },
        headers=_admin_header(),
    )
    assert r1.status_code == 202
    body1 = r1.json()
    task_id = body1["task_id"]

    r2 = client.post(
        f"/api/admin/sessions/{sid}/agents/{aid}/work",
        json={
            "_agflow_correlation_id": cid,
            "instruction": {"text": "different"},
        },
        headers=_admin_header(),
    )
    assert r2.status_code == 409
    body2 = r2.json()
    assert body2["detail"]["task_id"] == task_id


def test_delete_session_force_true_returns_204(client, fresh_db, mock_session):
    sid = mock_session
    response = client.delete(
        f"/api/admin/sessions/{sid}?force=true",
        headers=_admin_header(),
    )
    assert response.status_code == 204
```

**Note fixtures** : si les fixtures `mock_api_key`, `mock_hmac_key`, `mock_session`, `mock_session_with_runtime`, `mock_session_and_agent` n'existent pas dans `conftest.py`, l'implementer doit les créer (INSERT direct DB pour isoler des side-effects services).

### Step 2 — Verify fail

- [ ] Lancer : `cd backend && uv run pytest tests/api/test_admin_workflow_sessions.py -v`

### Step 3 — Écrire le router

- [ ] Créer `backend/src/agflow/api/admin/workflow_sessions.py` :

```python
"""Endpoints workflow contracts v5 — sessions/agents/work/delete."""
from __future__ import annotations

import json
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status

from agflow.auth.dependencies import require_operator_or_m2m
from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.mom.envelope import Direction
from agflow.mom.publisher import publisher  # à adapter selon l'API réelle
from agflow.schemas.workflow import (
    AgentCreateRequest,
    AgentCreateResponse,
    SessionCreateRequest,
    SessionCreateResponse,
    WorkRequest,
    WorkResponse,
)
from agflow.services import (
    agents_instances_service,
    hmac_keys_service,
    sessions_service,
    tasks_service,
)

_log = structlog.get_logger(__name__)

router = APIRouter(
    tags=["admin-workflow"],
    dependencies=[Depends(require_operator_or_m2m)],
)


@router.post(
    "/api/admin/sessions",
    response_model=SessionCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_session(payload: SessionCreateRequest) -> SessionCreateResponse:
    # Validation hmac_key_id existe
    if payload.callback_hmac_key_id is not None:
        if not await hmac_keys_service.exists(payload.callback_hmac_key_id):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"error": "hmac_key_not_found"},
            )

    # Validation project_runtime_id existe
    if payload.project_runtime_id is not None:
        runtime = await fetch_one(
            "SELECT id FROM project_runtimes WHERE id = $1",
            payload.project_runtime_id,
        )
        if runtime is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"error": "runtime_not_found"},
            )

    session = await sessions_service.create(
        api_key_id=payload.api_key_id,
        name=payload.name,
        duration_seconds=payload.duration_seconds,
    )
    # Mettre à jour les colonnes workflow (callback_url, callback_hmac_key_id, project_runtime_id)
    await execute(
        """
        UPDATE sessions
        SET project_runtime_id = $1,
            callback_url = $2,
            callback_hmac_key_id = $3
        WHERE id = $4
        """,
        payload.project_runtime_id,
        payload.callback_url,
        payload.callback_hmac_key_id,
        session["id"],
    )

    _log.info(
        "workflow.session.created",
        session_id=str(session["id"]),
        project_runtime_id=str(payload.project_runtime_id)
        if payload.project_runtime_id
        else None,
        has_callback=payload.callback_url is not None,
    )
    return SessionCreateResponse(
        session_id=session["id"],
        expires_at=session["expires_at"].isoformat(),
    )


@router.post(
    "/api/admin/sessions/{session_id}/agents",
    response_model=AgentCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_agents(
    session_id: UUID, payload: AgentCreateRequest
) -> AgentCreateResponse:
    # Récupérer la session + son runtime_id si lié
    session_row = await fetch_one(
        "SELECT project_runtime_id FROM sessions WHERE id = $1",
        session_id,
    )
    if session_row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "session_not_found"},
        )

    # Création standard via le service M5
    agent_ids = await agents_instances_service.create(
        session_id=session_id,
        agent_id=payload.agent_id,
        count=payload.count,
        labels=payload.labels,
        mission=payload.mission,
    )

    # Fusion MCP si session liée à runtime
    if session_row["project_runtime_id"] is not None:
        runtime_id = session_row["project_runtime_id"]
        instance_rows = await fetch_all(
            """
            SELECT i.mcp_bindings
            FROM instances i
            JOIN groups g ON g.id = i.group_id
            JOIN project_runtimes pr ON pr.project_id = g.project_id
            WHERE pr.id = $1
            """,
            runtime_id,
        )
        merged: list = []
        for r in instance_rows:
            mcp = r["mcp_bindings"]
            if isinstance(mcp, str):
                mcp = json.loads(mcp)
            if isinstance(mcp, list):
                merged.extend(mcp)

        for aid in agent_ids:
            await execute(
                "UPDATE agents_instances SET mcp_bindings_injected = $1::jsonb WHERE id = $2",
                json.dumps(merged),
                aid,
            )

    return AgentCreateResponse(agent_instance_ids=agent_ids)


@router.post(
    "/api/admin/sessions/{session_id}/agents/{agent_instance_id}/work",
    response_model=WorkResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def post_work(
    session_id: UUID,
    agent_instance_id: UUID,
    payload: WorkRequest,
) -> WorkResponse:
    task = await tasks_service.create_session_work(
        session_id=session_id,
        agent_instance_id=agent_instance_id,
        agflow_correlation_id=payload.agflow_correlation_id,
        instruction=payload.instruction,
    )
    if task["was_existing"]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": "duplicate_correlation_id",
                "task_id": str(task["task_id"]),
            },
        )

    # MOM publish — laisser l'implementer adapter l'API réelle si elle diffère.
    # Pattern attendu : publisher.publish(direction=IN, kind="instruction.work", ...)
    # Si l'API réelle requiert un envelope, construire-le ici.
    try:
        await publisher.publish(
            session_id=session_id,
            instance_id=agent_instance_id,
            direction=Direction.IN,
            kind="instruction.work",
            payload={
                "instruction": payload.instruction,
                "_agflow_correlation_id": str(payload.agflow_correlation_id),
                "_agflow_task_id": str(task["task_id"]),
            },
        )
    except Exception as exc:
        _log.exception(
            "workflow.work.mom_publish_failed", task_id=str(task["task_id"])
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"error": "mom_publish_failed", "message": str(exc)},
        ) from exc

    return WorkResponse(
        task_id=task["task_id"],
        agflow_correlation_id=payload.agflow_correlation_id,
    )


@router.delete(
    "/api/admin/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_session(
    session_id: UUID,
    force: bool = Query(default=False),
) -> None:
    # Sans force : retourne 409 si session pas active
    if not force:
        row = await fetch_one(
            "SELECT status FROM sessions WHERE id = $1", session_id
        )
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "session_not_found"},
            )
        if row["status"] != "active":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error": "session_not_active"},
            )

    # close() est-admin friendly : avec is_admin=True pas besoin de api_key_id
    await sessions_service.close(
        session_id=session_id,
        api_key_id=session_id,  # ignoré quand is_admin=True
        is_admin=True,
    )
```

**Note importante** : l'API réelle de `publisher.publish` peut différer du code ci-dessus. L'implementer doit :
1. Lire `backend/src/agflow/mom/publisher.py` pour la signature exacte.
2. Adapter le call ci-dessus en conséquence.
3. Si le pattern impose un `Envelope`, le construire avant l'appel.

### Step 4 — Brancher dans main.py

- [ ] Ajouter import + `include_router`.

### Step 5 — Re-lancer

- [ ] Lancer : `cd backend && uv run pytest tests/api/test_admin_workflow_sessions.py -v`
- [ ] Attendu : **5 PASS** (DONE_WITH_CONCERNS si DB injoignable).

### Step 6 — Lint

- [ ] Lancer : `cd backend && uv run ruff check src/agflow/api/admin/workflow_sessions.py src/agflow/main.py tests/api/test_admin_workflow_sessions.py`

### Step 7 — Commit

```bash
git add backend/src/agflow/api/admin/workflow_sessions.py \
         backend/src/agflow/main.py \
         backend/tests/api/test_admin_workflow_sessions.py
git commit -m "feat(workflow-api): POST sessions + POST agents (fusion MCP) + POST work + DELETE"
```

---

## Tâche 9 — Adapter DTO `GET /api/admin/projects` + validation E2E

**Files:**
- Modify: `backend/src/agflow/api/admin/projects.py` (adapter DTO + ajouter `resources_summary`)
- Validation E2E LXC fresh

### Step 1 — Adapter le DTO existant

- [ ] Ouvrir `backend/src/agflow/api/admin/projects.py`.
- [ ] Identifier les 2 endpoints `GET /` et `GET /{project_id}` qui retournent `ProjectSummary`.
- [ ] Ajouter une variante v5 du DTO (sans casser l'existant) :

```python
# En haut du fichier, à côté des autres imports schemas
from agflow.schemas.workflow import ProjectSummaryV5, ResourceSummary
```

- [ ] Ajouter 2 nouveaux endpoints v5 (sans toucher les existants) :

```python
@router.get("/v5/list", response_model=list[ProjectSummaryV5])
async def list_projects_v5() -> list[ProjectSummaryV5]:
    """Endpoint v5 contract-shaped : liste avec resources_summary."""
    projects = await projects_service.list_all()
    result = []
    for p in projects:
        groups = await groups_service.list_by_project(p.id)
        resources_summary = []
        for g in groups:
            instances = await product_instances_service.list_by_group(g.id)
            for i in instances:
                resources_summary.append(
                    ResourceSummary(type=i.catalog_id, label=i.instance_name)
                )
        result.append(
            ProjectSummaryV5(
                project_id=p.id,
                name=p.display_name,
                description=p.description,
                resources_summary=resources_summary,
            )
        )
    return result


@router.get("/v5/{project_id}", response_model=ProjectSummaryV5)
async def get_project_v5(project_id: UUID) -> ProjectSummaryV5:
    """Endpoint v5 contract-shaped : détail avec resources_summary."""
    try:
        project = await projects_service.get_by_id(project_id)
    except projects_service.ProjectNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    groups = await groups_service.list_by_project(project.id)
    resources_summary = []
    for g in groups:
        instances = await product_instances_service.list_by_group(g.id)
        for i in instances:
            resources_summary.append(
                ResourceSummary(type=i.catalog_id, label=i.instance_name)
            )
    return ProjectSummaryV5(
        project_id=project.id,
        name=project.display_name,
        description=project.description,
        resources_summary=resources_summary,
    )
```

**Note** : on n'écrase pas les endpoints existants (admin UI s'en sert). Les 2 nouveaux endpoints sont des routes parallèles `/v5/list` et `/v5/{id}` exposées pour le contrat workflow.

### Step 2 — Vérifier tests + lint

- [ ] Lancer : `cd backend && uv run pytest tests/api/test_admin_projects*.py -v` (si existe).
- [ ] Lancer : `cd backend && uv run ruff check src/agflow/api/admin/projects.py`

### Step 3 — Push origin/dev

- [ ] Lancer : `git push origin dev`

### Step 4 — Validation E2E LXC fresh

- [ ] Lancer : `./scripts/run-test.sh`
- [ ] Attendu :
  - LXC fresh créé
  - Code déployé
  - 8/8 assertions smoke
  - pytest complet vert (incluant les ~24 nouveaux tests workflow)

### Step 5 — Smoke API manuel (curl) sur LXC fresh

- [ ] Récupérer l'IP du LXC + le mot de passe admin dans la sortie.
- [ ] Tester via curl :

```bash
# Login
TOKEN=$(curl -sS -X POST "http://<IP>/api/admin/auth/login" \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@agflow.example.com","password":"<password>"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Test POST /api/admin/hmac-keys
curl -sS -X POST "http://<IP>/api/admin/hmac-keys" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"key_id":"smoke-1","secret_hex":"0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef","description":"smoke"}'
# Attendu : 201 + body

# Test conflit
curl -sS -X POST "http://<IP>/api/admin/hmac-keys" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"key_id":"smoke-1","secret_hex":"0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef","description":""}'
# Attendu : 409

# Test POST /api/admin/sessions sans api_key_id valide → 422 ou 500
# (réelle validation nécessite une api_key existante)
```

### Step 6 — Cleanup LXC

- [ ] Lancer : `ssh pve "pct stop <CTID> && pct destroy <CTID> --purge"`

### Step 7 — Mémoire des modules

- [ ] Mettre à jour `C:\Users\g.beard\.claude\projects\E--srcs-agflow-docker\memory\project_modules_status.md` : "Workflow Contracts" → "Tranche 1 livrée 2026-05-17, restent T2 (worker provisioning) + T3 (worker hook dispatcher)".

---

## Récapitulatif

**~10 commits livrés :**

1. `test(workflow): garde-fou présence tables/colonnes workflow contracts`
2. `feat(workflow-schemas): DTOs Pydantic v2 conformes contrat v5`
3. `feat(workflow-hmac): hmac_keys_service (CRUD + Fernet encrypt via harpocrate_dek)`
4. `feat(workflow-tasks): tasks_service (create_session_work idempotent + get)`
5. `feat(workflow-provisioning): provision_runtime + get_resources (sync simulé)`
6. `feat(workflow-api): POST /api/admin/hmac-keys`
7. `feat(workflow-api): POST /projects/{id}/runtimes + GET /project-runtimes/{id}/resources`
8. `feat(workflow-api): POST sessions + POST agents (fusion MCP) + POST work + DELETE`
9. `feat(workflow-projects-v5): GET /v5/list + GET /v5/{id} (DTO contrat v5)` (T9 step 1)
10. (commit final tag si nécessaire)

**~24 tests pytest** : 4 DB présence + 3 hmac_keys + 4 tasks + 3 provisioning + 2 API hmac + 3 API runtimes + 5 API sessions.

**Wall time estimé :** 3 jours en pipeline allégé (réduit de 4-5j initialement, car migration déjà en place).

**Aucune modification frontend** — tranche 1 100% backend.

**Hors scope explicite (différé tranche 2)** : worker provisioning Jinja, worker hook dispatcher HMAC + retry, hook task-completed côté outbound, DELETE hmac-keys, tests E2E contre mock-receiver ag.flow.
