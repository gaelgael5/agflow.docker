# Workflow Contracts — Tranche 4 (mock-receiver E2E + admin operations)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compléter le contrat workflow v5 par 2 endpoints d'administration (`DELETE /api/admin/hmac-keys/{key_id}` pour rotation, `GET /api/admin/tasks/{task_id}` pour query status) + valider bout-en-bout l'émission HMAC du hook task-completed via un mock-receiver containerisé intégré à `run-test.sh`. À la fin de T4, le flow E2E complet (POST work → MOM result → outbound_hooks → dispatcher POST signé HMAC → mock-receiver vérifie signature) doit passer sur LXC fresh.

**Architecture:** Le **mock-receiver** est un container FastAPI minimal (~70 lignes) basé sur `docs/contracts/mock-docker/hook_receiver.py` qui existe déjà comme référence. On l'ajoute au `docker-compose.dev.yml` (utilisé par `dev-deploy.sh` invoqué par `run-test.sh`) sous le service `mock-receiver`, exposé en interne sur `http://mock-receiver:8001`. Il vérifie la signature HMAC reçue + idempotence + stocke chaque hook accepté en mémoire, et expose `GET /hooks` pour permettre aux assertions bash de vérifier le bon nombre/contenu. Les 2 endpoints admin sont ajoutés au router `workflow_hmac_keys.py` (DELETE) et un nouveau `workflow_tasks.py` (GET).

**Tech Stack:** Python 3.12 + FastAPI (mock) + asyncpg + Pydantic v2 + bash assertions. Pas de nouvelles dépendances.

**Spec de référence :**
- `docs/contracts/hook-docker-task-completed.md` v5 — schéma body, signature
- `docs/contracts/docker-orchestration-flow.md` v5 — endpoints admin
- `docs/contracts/mock-docker/hook_receiver.py` — modèle existant à adapter

**Branche cible :** `dev`. Pas de feature branch.

**Décisions de cadrage (héritées T1-T3) :**
- Workers asyncio (déjà en place), mock-receiver dans un container dédié au compose dev.
- Validation E2E via curl + assertions bash dans run-test.sh (pas pytest pour l'E2E inter-container).
- Le mock partage la même clé HMAC qu'agflow.docker via variable d'env `HOOK_HMAC_KEY` + insert manuel de la row `hmac_keys` avec un secret connu.
- DELETE hmac-keys = soft-delete (set `rotated_at=now()`), pas suppression physique — préserve l'historique pour audit/forensics.
- GET tasks = lecture seule, retourne le shape contrat v5 §3.7 (task_id, status, result, error, timing) + le `agflow_correlation_id` pour permettre à ag.flow de re-corréler après un crash.

**Politique git :** chaque tâche se termine par `git commit` **suivi de `git push origin dev`** (même politique que T2 et T3).

**Note tests** :
- Tests pytest API peuvent retourner DONE_WITH_CONCERNS sur dev Windows (LXC injoignable).
- Validation finale via `./scripts/run-test.sh` à T4.6 avec les nouvelles assertions E2E inter-container.

---

## Structure des fichiers (vue d'ensemble)

### Backend (3 nouveaux + 2 modifs)

| Fichier | Responsabilité | Lignes |
|---|---|---|
| `backend/src/agflow/api/admin/workflow_hmac_keys.py` (modif) | Ajout `DELETE /api/admin/hmac-keys/{key_id}` | +35 |
| `backend/src/agflow/services/hmac_keys_service.py` (modif) | Ajout `mark_rotated(key_id)` | +25 |
| `backend/src/agflow/api/admin/workflow_tasks.py` (nouveau) | `GET /api/admin/tasks/{task_id}` | ~70 |
| `backend/src/agflow/schemas/workflow.py` (modif) | Ajout `TaskStatusResponse` | +15 |
| `backend/src/agflow/main.py` (modif) | `include_router(admin_workflow_tasks_router)` | +2 |

### Mock-receiver (3 nouveaux)

| Fichier | Responsabilité | Lignes |
|---|---|---|
| `tools/mock-receiver/app.py` (nouveau) | FastAPI : POST hook receiver + GET /hooks + GET /health | ~120 |
| `tools/mock-receiver/Dockerfile` (nouveau) | python:3.12-slim + uvicorn + fastapi | ~15 |
| `tools/mock-receiver/requirements.txt` (nouveau) | fastapi, uvicorn[standard] | ~3 |

### Infra & scripts (2 modifs)

| Fichier | Responsabilité | Lignes |
|---|---|---|
| `docker-compose.dev.yml` (modif) | Ajout service `mock-receiver` (build + env + port interne) | +12 |
| `scripts/run-test.sh` (modif) | Étape 7.9 : assertions E2E flow workflow complet avec hook signed | +60 |

### Tests (3 fichiers nouveaux)

| Fichier | Tests |
|---|---|
| `backend/tests/services/test_hmac_keys_mark_rotated.py` | 3 : mark_rotated set rotated_at, idempotent, unknown key raises |
| `backend/tests/api/test_admin_hmac_keys_delete.py` | 3 : DELETE 204, idempotent, unknown 404 |
| `backend/tests/api/test_admin_workflow_tasks.py` | 4 : GET completed task returns full shape, GET failed returns error, GET pending returns minimal, GET unknown 404 |

**Total : 10 tests pytest + 4-6 assertions bash E2E.**

---

## Tâche 1 — `hmac_keys_service.mark_rotated` (soft-delete)

**Files:**
- Modify: `backend/src/agflow/services/hmac_keys_service.py`
- Create: `backend/tests/services/test_hmac_keys_mark_rotated.py`

### Step 1 — Écrire les tests

- [ ] Créer `backend/tests/services/test_hmac_keys_mark_rotated.py` :

```python
"""Tests de hmac_keys_service.mark_rotated (soft-delete)."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_mark_rotated_sets_rotated_at(fresh_db):
    from agflow.services import hmac_keys_service

    key_id = "test-rotate-1"
    await hmac_keys_service.create(
        key_id=key_id, secret_hex="0123456789abcdef" * 4, description=""
    )
    await hmac_keys_service.mark_rotated(key_id=key_id)

    row = await fresh_db.fetchrow(
        "SELECT rotated_at FROM hmac_keys WHERE key_id = $1", key_id
    )
    assert row is not None
    assert row["rotated_at"] is not None


async def test_mark_rotated_idempotent(fresh_db):
    """Appeler 2× mark_rotated n'écrase pas la 1ère date (préserve l'historique)."""
    from agflow.services import hmac_keys_service

    key_id = "test-rotate-idem"
    await hmac_keys_service.create(
        key_id=key_id, secret_hex="0123456789abcdef" * 4, description=""
    )
    await hmac_keys_service.mark_rotated(key_id=key_id)
    first_row = await fresh_db.fetchrow(
        "SELECT rotated_at FROM hmac_keys WHERE key_id = $1", key_id
    )
    first_ts = first_row["rotated_at"]

    await hmac_keys_service.mark_rotated(key_id=key_id)
    second_row = await fresh_db.fetchrow(
        "SELECT rotated_at FROM hmac_keys WHERE key_id = $1", key_id
    )
    assert second_row["rotated_at"] == first_ts  # inchangé


async def test_mark_rotated_unknown_raises(fresh_db):
    from agflow.services import hmac_keys_service

    with pytest.raises(hmac_keys_service.HmacKeyNotFoundError):
        await hmac_keys_service.mark_rotated(key_id="nonexistent")
```

### Step 2 — Étendre le service

- [ ] Ouvrir `backend/src/agflow/services/hmac_keys_service.py` et ajouter à la fin (avant les exports) :

```python
async def mark_rotated(*, key_id: str) -> None:
    """Marque une hmac_key comme rotated (soft-delete).

    Idempotent : si déjà rotated, ne fait rien (préserve la date originale).
    Raise HmacKeyNotFoundError si la clé n'existe pas du tout.
    """
    row = await fetch_one(
        """
        UPDATE hmac_keys
        SET rotated_at = now()
        WHERE key_id = $1 AND rotated_at IS NULL
        RETURNING key_id
        """,
        key_id,
    )
    if row is None:
        # Soit clé inexistante, soit déjà rotated → distinguer
        existing = await fetch_one(
            "SELECT key_id FROM hmac_keys WHERE key_id = $1", key_id
        )
        if existing is None:
            raise HmacKeyNotFoundError(f"hmac key '{key_id}' not found")
        # Déjà rotated → idempotence, pas d'erreur
        return
    _log.info("workflow.hmac_key.rotated", key_id=key_id)
```

### Step 3 — Lint + pytest

- [ ] `cd backend && uv run ruff check src/agflow/services/hmac_keys_service.py tests/services/test_hmac_keys_mark_rotated.py`
- [ ] `cd backend && uv run pytest tests/services/test_hmac_keys_mark_rotated.py -v` — DB unreachable acceptable.

### Step 4 — Commit + push

```bash
git add backend/src/agflow/services/hmac_keys_service.py \
        backend/tests/services/test_hmac_keys_mark_rotated.py
git commit -m "feat(workflow-t4): hmac_keys_service.mark_rotated (soft-delete idempotent)"
git push origin dev
```

---

## Tâche 2 — Endpoint `DELETE /api/admin/hmac-keys/{key_id}`

**Files:**
- Modify: `backend/src/agflow/api/admin/workflow_hmac_keys.py` (the file name in T1 was `hmac_keys.py` — verify exact path)
- Create: `backend/tests/api/test_admin_hmac_keys_delete.py`

### Step 1 — Écrire les tests

- [ ] Créer `backend/tests/api/test_admin_hmac_keys_delete.py` :

```python
"""Tests de DELETE /api/admin/hmac-keys/{key_id}."""
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


def test_delete_existing_hmac_key_returns_204(client, fresh_db):
    payload = {
        "key_id": "delete-test-1",
        "secret_hex": "0123456789abcdef" * 4,
        "description": "",
    }
    r1 = client.post("/api/admin/hmac-keys", json=payload, headers=_admin_header())
    assert r1.status_code == 201

    r2 = client.delete(
        "/api/admin/hmac-keys/delete-test-1", headers=_admin_header()
    )
    assert r2.status_code == 204


def test_delete_unknown_hmac_key_returns_404(client, fresh_db):
    r = client.delete(
        "/api/admin/hmac-keys/nonexistent", headers=_admin_header()
    )
    assert r.status_code == 404


def test_delete_idempotent_returns_204(client, fresh_db):
    """2× DELETE sur la même clé → 204 puis 204 (idempotence)."""
    payload = {
        "key_id": "delete-idem",
        "secret_hex": "0123456789abcdef" * 4,
        "description": "",
    }
    client.post("/api/admin/hmac-keys", json=payload, headers=_admin_header())

    r1 = client.delete(
        "/api/admin/hmac-keys/delete-idem", headers=_admin_header()
    )
    r2 = client.delete(
        "/api/admin/hmac-keys/delete-idem", headers=_admin_header()
    )
    assert r1.status_code == 204
    assert r2.status_code == 204  # idempotence : déjà rotated → toujours 204
```

### Step 2 — Ajouter l'endpoint

- [ ] Ouvrir le fichier qui contient `POST /api/admin/hmac-keys` (de T1 — probablement `backend/src/agflow/api/admin/hmac_keys.py`). Ajouter :

```python
@router.delete(
    "/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_hmac_key(key_id: str) -> None:
    """Soft-delete : marque la clé comme rotated (préserve l'historique).

    Idempotent : 204 même si déjà rotated.
    404 uniquement si la clé n'existe pas du tout.
    """
    try:
        await hmac_keys_service.mark_rotated(key_id=key_id)
    except hmac_keys_service.HmacKeyNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "hmac_key_not_found", "message": str(exc)},
        ) from exc
```

### Step 3 — Lint + pytest

- [ ] `cd backend && uv run ruff check src/agflow/api/admin/hmac_keys.py tests/api/test_admin_hmac_keys_delete.py`
- [ ] `cd backend && uv run pytest tests/api/test_admin_hmac_keys_delete.py -v`

### Step 4 — Commit + push

```bash
git add backend/src/agflow/api/admin/hmac_keys.py \
        backend/tests/api/test_admin_hmac_keys_delete.py
git commit -m "feat(workflow-t4): DELETE /api/admin/hmac-keys/{key_id} (soft-delete)"
git push origin dev
```

---

## Tâche 3 — Endpoint `GET /api/admin/tasks/{task_id}`

**Files:**
- Create: `backend/src/agflow/api/admin/workflow_tasks.py`
- Modify: `backend/src/agflow/schemas/workflow.py` (ajout `TaskStatusResponse`)
- Modify: `backend/src/agflow/main.py` (include_router)
- Create: `backend/tests/api/test_admin_workflow_tasks.py`

### Step 1 — Étendre le schéma

- [ ] Ouvrir `backend/src/agflow/schemas/workflow.py` et ajouter en fin de fichier :

```python
class TaskStatusResponse(BaseModel):
    """Shape conforme contrat v5 §3.7 + champs de corrélation pour ag.flow recovery."""
    task_id: UUID
    kind: str
    status: str = Field(description="pending | running | completed | failed | cancelled")
    session_id: UUID | None = None
    agent_instance_id: UUID | None = None
    agflow_correlation_id: UUID | None = None
    agflow_action_execution_id: UUID | None = None
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    started_at: str | None = None
    completed_at: str | None = None
    created_at: str
```

### Step 2 — Écrire les tests

- [ ] Créer `backend/tests/api/test_admin_workflow_tasks.py` :

```python
"""Tests de GET /api/admin/tasks/{task_id}."""
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


@pytest.mark.asyncio
async def test_get_completed_task_returns_full_shape(
    client, fresh_db, mock_session_and_agent
):
    from agflow.services import tasks_service

    sid, aid = mock_session_and_agent
    cid = uuid4()
    aeid = uuid4()
    created = await tasks_service.create_session_work(
        session_id=sid,
        agent_instance_id=aid,
        agflow_correlation_id=cid,
        agflow_action_execution_id=aeid,
        instruction={"text": "x"},
    )
    await tasks_service.mark_completed(
        task_id=created["task_id"], result={"summary": "done"}
    )

    r = client.get(
        f"/api/admin/tasks/{created['task_id']}", headers=_admin_header()
    )
    assert r.status_code == 200
    body = r.json()
    assert body["task_id"] == str(created["task_id"])
    assert body["status"] == "completed"
    assert body["result"] == {"summary": "done"}
    assert body["error"] is None
    assert body["agflow_correlation_id"] == str(cid)
    assert body["agflow_action_execution_id"] == str(aeid)
    assert body["completed_at"] is not None


@pytest.mark.asyncio
async def test_get_failed_task_returns_error(
    client, fresh_db, mock_session_and_agent
):
    from agflow.services import tasks_service

    sid, aid = mock_session_and_agent
    created = await tasks_service.create_session_work(
        session_id=sid,
        agent_instance_id=aid,
        agflow_correlation_id=uuid4(),
        agflow_action_execution_id=uuid4(),
        instruction={},
    )
    await tasks_service.mark_failed(
        task_id=created["task_id"],
        error={"code": "AGENT_OOM", "message": "oom"},
    )

    r = client.get(
        f"/api/admin/tasks/{created['task_id']}", headers=_admin_header()
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "failed"
    assert body["error"]["code"] == "AGENT_OOM"
    assert body["result"] is None


@pytest.mark.asyncio
async def test_get_pending_task_returns_minimal(
    client, fresh_db, mock_session_and_agent
):
    from agflow.services import tasks_service

    sid, aid = mock_session_and_agent
    created = await tasks_service.create_session_work(
        session_id=sid,
        agent_instance_id=aid,
        agflow_correlation_id=uuid4(),
        agflow_action_execution_id=uuid4(),
        instruction={},
    )

    r = client.get(
        f"/api/admin/tasks/{created['task_id']}", headers=_admin_header()
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "pending"
    assert body["completed_at"] is None
    assert body["result"] is None


def test_get_unknown_task_returns_404(client, fresh_db):
    r = client.get(
        f"/api/admin/tasks/{uuid4()}", headers=_admin_header()
    )
    assert r.status_code == 404
```

### Step 3 — Écrire le router

- [ ] Créer `backend/src/agflow/api/admin/workflow_tasks.py` :

```python
"""Endpoint GET /api/admin/tasks/{task_id} (status query workflow v5)."""
from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, status

from agflow.auth.dependencies import require_operator_or_m2m
from agflow.schemas.workflow import TaskStatusResponse
from agflow.services import tasks_service

_log = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/admin/tasks",
    tags=["admin-workflow"],
    dependencies=[Depends(require_operator_or_m2m)],
)


@router.get(
    "/{task_id}",
    response_model=TaskStatusResponse,
)
async def get_task_status(task_id: UUID) -> TaskStatusResponse:
    task = await tasks_service.get_by_id(task_id)
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "task_not_found"},
        )

    return TaskStatusResponse(
        task_id=task["task_id"],
        kind=task["kind"],
        status=task["status"],
        session_id=task.get("session_id"),
        agent_instance_id=task.get("agent_instance_id"),
        agflow_correlation_id=task.get("agflow_correlation_id"),
        agflow_action_execution_id=task.get("agflow_action_execution_id"),
        result=task.get("result"),
        error=task.get("error"),
        started_at=task["started_at"].isoformat() if task.get("started_at") else None,
        completed_at=task["completed_at"].isoformat() if task.get("completed_at") else None,
        created_at=task["created_at"].isoformat(),
    )
```

> **Note** : `tasks_service.get_by_id` (T1) ne retourne PAS aujourd'hui `agflow_action_execution_id`. Il faut l'ajouter au SELECT de `get_by_id`. Modifier `tasks_service.get_by_id` pour inclure cette colonne + la retourner dans le dict.

### Step 4 — Wire-up + lint + tests

- [ ] Ajouter dans `backend/src/agflow/main.py` :

```python
from agflow.api.admin.workflow_tasks import router as admin_workflow_tasks_router
# ...
app.include_router(admin_workflow_tasks_router)
```

- [ ] Lint + pytest.

### Step 5 — Commit + push

```bash
git add backend/src/agflow/api/admin/workflow_tasks.py \
        backend/src/agflow/services/tasks_service.py \
        backend/src/agflow/schemas/workflow.py \
        backend/src/agflow/main.py \
        backend/tests/api/test_admin_workflow_tasks.py
git commit -m "feat(workflow-t4): GET /api/admin/tasks/{task_id} (status query v5)"
git push origin dev
```

---

## Tâche 4 — Mock-receiver containerisé

**Files:**
- Create: `tools/mock-receiver/app.py`
- Create: `tools/mock-receiver/Dockerfile`
- Create: `tools/mock-receiver/requirements.txt`
- Create: `tools/mock-receiver/README.md`

### Step 1 — Créer la structure

- [ ] `mkdir -p tools/mock-receiver`
- [ ] Créer `tools/mock-receiver/requirements.txt` :

```
fastapi>=0.115
uvicorn[standard]>=0.30
```

- [ ] Créer `tools/mock-receiver/Dockerfile` :

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
EXPOSE 8001
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8001"]
```

### Step 2 — Écrire le mock-receiver

- [ ] Créer `tools/mock-receiver/app.py` (adapté de `docs/contracts/mock-docker/hook_receiver.py`) :

```python
"""Mock-receiver — simule ag.flow pour les tests E2E workflow.

Utilisé par run-test.sh pour valider que le hook task-completed est :
- POSTé sur le bon URL
- Avec les 3 headers HMAC valides
- Avec une signature HMAC SHA-256 correcte
- Idempotent sur replay (hook_id seen)

Variables d'env :
    HOOK_HMAC_KEY                 Clé partagée (default: secret_v1)
    HOOK_REPLAY_WINDOW_SECONDS    Tolérance anti-replay (default: 300)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="Mock receiver (workflow E2E)", version="5.0.0")

SHARED_SECRET = os.environ.get("HOOK_HMAC_KEY", "secret_v1")
REPLAY_WINDOW_S = int(os.environ.get("HOOK_REPLAY_WINDOW_SECONDS", "300"))

# État en mémoire (mock — pas persistant)
SEEN_HOOK_IDS: set[str] = set()
RECEIVED_HOOKS: list[dict[str, Any]] = []


def _verify_signature(timestamp: str, hook_id: str, raw_body: bytes, header: str) -> bool:
    if not header.startswith("hmac-sha256="):
        return False
    given = header.split("=", 1)[1]
    msg = (timestamp + "\n" + hook_id + "\n").encode("utf-8") + raw_body
    expected = hmac.new(
        SHARED_SECRET.encode("utf-8"), msg, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, given)


def _verify_timestamp(ts: str) -> bool:
    try:
        sent = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return False
    age = abs((datetime.now(UTC) - sent).total_seconds())
    return age <= REPLAY_WINDOW_S


@app.post("/api/v1/hooks/docker/task-completed")
async def receive_hook(request: Request) -> JSONResponse:
    raw = await request.body()
    hook_id = request.headers.get("x-agflow-hook-id", "")
    timestamp = request.headers.get("x-agflow-timestamp", "")
    signature = request.headers.get("x-agflow-signature", "")

    if not _verify_timestamp(timestamp):
        return JSONResponse({"error": "timestamp_replay"}, status_code=401)

    if not _verify_signature(timestamp, hook_id, raw, signature):
        return JSONResponse({"error": "bad_signature"}, status_code=401)

    if hook_id in SEEN_HOOK_IDS:
        return JSONResponse({"ok": True, "duplicate": True})

    SEEN_HOOK_IDS.add(hook_id)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return JSONResponse({"error": "bad_json"}, status_code=400)

    RECEIVED_HOOKS.append({
        "hook_id": hook_id,
        "timestamp": timestamp,
        "signature": signature,
        "payload": payload,
        "received_at": datetime.now(UTC).isoformat(),
    })
    return JSONResponse({"ok": True})


@app.get("/hooks")
async def list_hooks() -> dict:
    """Expose les hooks reçus pour les assertions bash de run-test.sh."""
    return {
        "count": len(RECEIVED_HOOKS),
        "hooks": RECEIVED_HOOKS,
    }


@app.delete("/hooks")
async def clear_hooks() -> dict:
    """Reset l'état mémoire (utile entre runs E2E)."""
    SEEN_HOOK_IDS.clear()
    RECEIVED_HOOKS.clear()
    return {"ok": True}


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "received_count": len(RECEIVED_HOOKS)}
```

### Step 3 — README

- [ ] Créer `tools/mock-receiver/README.md` :

```markdown
# Mock-receiver (workflow E2E)

Container FastAPI minimal qui simule le récepteur de hooks `ag.flow` côté
agflow.docker. Utilisé par `scripts/run-test.sh` pour valider bout-en-bout
l'émission HMAC du `hook_dispatcher_worker`.

## Endpoints

- `POST /api/v1/hooks/docker/task-completed` — vérifie HMAC + idempotence + stocke le hook
- `GET /hooks` — liste les hooks reçus (assertions bash)
- `DELETE /hooks` — reset état (entre runs)
- `GET /health` — healthcheck

## Variables d'env

- `HOOK_HMAC_KEY` : secret partagé avec agflow.docker (doit matcher la row `hmac_keys` créée par le test)
- `HOOK_REPLAY_WINDOW_SECONDS` : tolérance anti-replay (default 300s)

## Démarrage local (debug)

```bash
HOOK_HMAC_KEY=test_secret uv run uvicorn app:app --port 8001
```

## Démarrage via compose

Voir `docker-compose.dev.yml` service `mock-receiver`.
```

### Step 4 — Lint Python

- [ ] `cd tools/mock-receiver && python -m py_compile app.py` (syntax check sans uv)

### Step 5 — Commit + push

```bash
git add tools/mock-receiver/
git commit -m "feat(workflow-t4): mock-receiver containerisé pour tests E2E HMAC"
git push origin dev
```

---

## Tâche 5 — Intégration mock-receiver au docker-compose.dev.yml + extension run-test.sh

**Files:**
- Modify: `docker-compose.dev.yml`
- Modify: `scripts/run-test.sh`

### Step 1 — Ajouter le service au compose

- [ ] Ouvrir `docker-compose.dev.yml`. Ajouter une nouvelle section dans `services:` :

```yaml
  mock-receiver:
    build:
      context: ./tools/mock-receiver
      dockerfile: Dockerfile
    container_name: agflow-mock-receiver
    networks:
      - agflow
    environment:
      HOOK_HMAC_KEY: ${WORKFLOW_TEST_HMAC_SECRET:-0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef}
    expose:
      - "8001"
    restart: unless-stopped
```

**Note** : le `HOOK_HMAC_KEY` doit matcher le secret utilisé pour créer la row `hmac_keys` côté agflow.docker dans le test E2E. On utilise un secret fixe `0123456789abcdef...` × 4 (64 chars hex).

### Step 2 — Étendre run-test.sh avec les assertions E2E

- [ ] Ouvrir `scripts/run-test.sh`. Identifier la section ÉTAPE 7 (Validation) après le `[PASS] Suite pytest backend`. Ajouter une section ÉTAPE 7.9 (E2E workflow hook) avant l'ÉTAPE 8 Nettoyage :

```bash
echo "[$(date +%H:%M:%S)] === ÉTAPE 7.9 : Validation E2E workflow hook ==="

LXC_IP="${LXC_IP:-$(pct exec "$CTID" -- hostname -I | awk '{print $1}')}"
ADMIN_PASS="${ADMIN_PASSWORD}"  # déjà exporté par dev-deploy.sh
WORKFLOW_HMAC_SECRET="0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

# Vérifier que mock-receiver répond
if ! pct exec "$CTID" -- curl -sf http://mock-receiver:8001/health > /dev/null; then
    echo "  [FAIL] mock-receiver health check"
    exit 1
fi
echo "  [PASS] mock-receiver health OK"

# Reset état mock entre runs
pct exec "$CTID" -- curl -sX DELETE http://mock-receiver:8001/hooks > /dev/null

# Login admin
TOKEN=$(pct exec "$CTID" -- curl -sS -X POST "http://localhost/api/admin/auth/login" \
    -H 'Content-Type: application/json' \
    -d "{\"email\":\"admin@agflow.example.com\",\"password\":\"$ADMIN_PASS\"}" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

if [ -z "$TOKEN" ]; then
    echo "  [FAIL] admin login"
    exit 1
fi

# Créer une hmac_key (id=e2e-test, secret=WORKFLOW_HMAC_SECRET)
HMAC_RESP=$(pct exec "$CTID" -- curl -sS -X POST "http://localhost/api/admin/hmac-keys" \
    -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
    -d "{\"key_id\":\"e2e-test\",\"secret_hex\":\"$WORKFLOW_HMAC_SECRET\",\"description\":\"E2E\"}")

if ! echo "$HMAC_RESP" | grep -q "e2e-test"; then
    echo "  [FAIL] POST /hmac-keys : $HMAC_RESP"
    exit 1
fi
echo "  [PASS] POST /hmac-keys e2e-test créée"

# Smoke E2E : on n'a pas de session/agent/work facile à scripter en bash
# (pas de produit dans le catalogue, pas d'agent_id valide).
# On valide via l'insertion DIRECTE d'une row outbound_hooks et la vérification
# que le dispatcher la prend en charge + le mock reçoit le hook signé.

HOOK_ID=$(pct exec "$CTID" -- uuidgen)
pct exec "$CTID" -- docker compose -f /opt/agflow.docker/docker-compose.dev.yml exec -T postgres \
    psql -U postgres -d agflow -c \
    "INSERT INTO outbound_hooks (hook_id, task_id, callback_url, hmac_key_id, payload, status, attempt_number, next_retry_at) VALUES ('$HOOK_ID', NULL, 'http://mock-receiver:8001/api/v1/hooks/docker/task-completed', 'e2e-test', '{\"status\":\"completed\",\"summary\":\"e2e test\"}'::jsonb, 'pending', 0, now())" \
    > /dev/null

echo "  [PASS] outbound_hooks row insérée (hook_id=$HOOK_ID)"

# Wait dispatcher poll (interval 2s + marge)
sleep 5

# Assert mock-receiver a reçu le hook
HOOKS_JSON=$(pct exec "$CTID" -- curl -sS http://mock-receiver:8001/hooks)
COUNT=$(echo "$HOOKS_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['count'])")

if [ "$COUNT" = "1" ]; then
    echo "  [PASS] mock-receiver a reçu 1 hook signé HMAC validé"
else
    echo "  [FAIL] mock-receiver count=$COUNT (attendu 1) — payload: $HOOKS_JSON"
    exit 1
fi

# Assert outbound_hooks marqué delivered
HOOK_STATUS=$(pct exec "$CTID" -- docker compose -f /opt/agflow.docker/docker-compose.dev.yml exec -T postgres \
    psql -U postgres -d agflow -tAc \
    "SELECT status FROM outbound_hooks WHERE hook_id = '$HOOK_ID'")

if [ "$HOOK_STATUS" = "delivered" ]; then
    echo "  [PASS] outbound_hooks row mark_delivered"
else
    echo "  [FAIL] outbound_hooks status=$HOOK_STATUS (attendu delivered)"
    exit 1
fi

echo "  [PASS] E2E workflow hook OK"
```

**Note** : adapter le script à la structure exacte de `run-test.sh` (l'invocation des `pct exec` peut être enveloppée différemment). Bien intégrer aux 8 assertions existantes — peut-être ajouter ces 4 assertions au compteur Tests OK / FAIL.

### Step 3 — Commit + push

```bash
git add docker-compose.dev.yml scripts/run-test.sh
git commit -m "feat(workflow-t4): mock-receiver compose + 4 assertions E2E hook signed"
git push origin dev
```

---

## Tâche 6 — Vérification finale + push global

### Step 1 — pytest collect-only + ruff global ciblé

- [ ] `cd backend && uv run pytest --collect-only -q 2>&1 | tail -10` — confirm ~910 tests collected (vs 901 fin T3).
- [ ] `cd backend && uv run ruff check src/agflow/api/admin/hmac_keys.py src/agflow/api/admin/workflow_tasks.py src/agflow/services/hmac_keys_service.py src/agflow/schemas/workflow.py tests/services/test_hmac_keys_mark_rotated.py tests/api/test_admin_hmac_keys_delete.py tests/api/test_admin_workflow_tasks.py`

### Step 2 — Vérifier que tous les commits sont pushés

- [ ] `git log origin/dev..dev` — empty.

---

## Tâche 7 — Validation E2E LXC fresh

### Step 1 — Lancer run-test.sh

- [ ] `./scripts/run-test.sh`
- [ ] Attendu :
  - LXC fresh créé
  - Migration appliquées (001 + 002)
  - pytest backend exit 0 (~910 tests passed)
  - Smoke 8/8 PASS (les 8 existantes)
  - **Nouvelle section ÉTAPE 7.9 E2E workflow hook** : 4 assertions PASS
  - Statut OK SUCCES

### Step 2 — Smoke curl additionnel (optionnel)

- [ ] Vérifier `GET /api/admin/tasks/{task_id}` via curl sur une task existante.
- [ ] Vérifier `DELETE /api/admin/hmac-keys/e2e-test` retourne 204.

### Step 3 — Cleanup LXC

- [ ] `ssh pve "pct stop <CTID> && pct destroy <CTID> --purge"`

### Step 4 — Mise à jour mémoire

- [ ] `memory/project_modules_status.md` : "Workflow Contracts Tranche 4 livrée 2026-05-{jj}".

---

## Récapitulatif

**~7 commits livrés :**

1. `feat(workflow-t4): hmac_keys_service.mark_rotated (soft-delete idempotent)`
2. `feat(workflow-t4): DELETE /api/admin/hmac-keys/{key_id} (soft-delete)`
3. `feat(workflow-t4): GET /api/admin/tasks/{task_id} (status query v5)`
4. `feat(workflow-t4): mock-receiver containerisé pour tests E2E HMAC`
5. `feat(workflow-t4): mock-receiver compose + 4 assertions E2E hook signed`

**~10 tests pytest** + **4 nouvelles assertions bash** dans run-test.sh.

**Wall time estimé :** 2-3 jours.

**Hors scope T4 (différé / future tranche) :**
- Mock-receiver versionné/publié (V1 = container build local uniquement)
- Pagination `GET /tasks` (liste filtrable) — V1 = lookup par ID uniquement
- Rotation automatique des hmac-keys via cron — manuel via DELETE
- Métriques structurées du dispatcher (taux de réussite, latence p95) — v2 supervision
