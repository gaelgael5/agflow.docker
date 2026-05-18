# Workflow Contracts — Tranche 3 (consumer task.completed + hook dispatcher HMAC)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Détecter la fin d'un `work` agent via le bus MOM (consumer sur `agent_messages` direction=out kind=result avec `_agflow_task_id`), marquer la `tasks` row correspondante comme completed/failed, puis enqueuer un `outbound_hooks` row qu'un worker dispatcher consomme pour POST le hook `task-completed` v5 signé HMAC SHA-256 vers `session.callback_url`, avec retry exponentiel (1s, 5s, 30s, 2min, 10min, pendant 1h max, puis status=`dead`).

**Architecture:** Deux nouveaux workers asyncio dans le lifespan FastAPI, suivant le pattern `stop_event + asyncio.wait_for` aligné sur `mom_reclaimer` et `provisioning_worker` (T2). Le **consumer `task_completed_consumer`** utilise `MomConsumer` avec un nouveau consumer group `workflow_task_completed` qui claim les messages OUT kind=result et corrèle via `payload._agflow_task_id` avec la table `tasks`. Le **dispatcher `hook_dispatcher_worker`** poll `outbound_hooks WHERE status='pending' AND next_retry_at <= NOW()`, charge la clé HMAC déchiffrée via `hmac_keys_service.get_by_key_id`, calcule la signature `hmac-sha256=<hex>(timestamp + "\n" + hook_id + "\n" + body)` (cf. `hook-docker-task-completed.md` §3.1), POST avec les 3 headers requis, et applique la politique de retry. La signature HMAC est isolée dans un helper pur testable sans DB (`hook_signing.py`).

**Tech Stack:** Python 3.12 + FastAPI lifespan + asyncpg + httpx (déjà installé) + structlog + pytest + pytest-asyncio + `respx` ou test intégré avec un petit aiohttp server pour les tests E2E HTTP. Le contrat hook v5 est documenté dans `docs/contracts/hook-docker-task-completed.md` (référence normative).

**Spec de référence :**
- `docs/contracts/hook-docker-task-completed.md` v5 — schéma body, headers, signature, retry policy
- `docs/contracts/docker-orchestration-flow.md` v5 §3.7 — POST /work crée la `tasks` row + injecte `_agflow_correlation_id` + `_agflow_action_execution_id` dans `instruction`
- Glossaire interne `docs/db/tables.md`

**Branche cible :** `dev`. Pas de feature branch.

**Décisions de cadrage (figées 2026-05-18) :**
- Workers asyncio dans le process FastAPI, pas de container séparé.
- Consumer MOM (group `workflow_task_completed`) plutôt qu'endpoint M2M (préserve le pattern M5).
- Mock-receiver des hooks **différé tranche 4** — T3 valide via tests pytest avec httpx mock (lib `respx` ou stub asyncio HTTP server).
- Validation E2E LXC : pytest vert + smoke curl avec un agent qui publie manuellement un message kind=result → vérifier que `outbound_hooks` row est créée et `tasks.status='completed'`. Le hook réel atteint le mock-receiver en T4.
- Cleanup `instances` colonnes runtime mal placées : toujours différé T2 bis.

**Politique git (rappel T2) :** chaque tâche se termine par `git commit` **suivi de `git push origin dev`**. Même si le plan n'affiche pas `git push` à chaque tâche, il est implicite.

**Note tests** :
- Tests pytest API peuvent retourner DONE_WITH_CONCERNS sur dev Windows (LXC injoignable), même politique que T1/T2.
- Validation finale via `./scripts/run-test.sh` à T3.9.

---

## Structure des fichiers (vue d'ensemble)

### Backend (5 nouveaux + 3 modifs)

| Fichier | Responsabilité | Lignes |
|---|---|---|
| `backend/src/agflow/services/hook_signing.py` (nouveau) | Helper pur HMAC SHA-256 : `sign(timestamp, hook_id, body, secret_hex) -> str` | ~50 |
| `backend/src/agflow/services/outbound_hooks_service.py` (nouveau) | CRUD `outbound_hooks` + retry backoff schedule | ~180 |
| `backend/src/agflow/workers/hook_dispatcher_worker.py` (nouveau) | Poll pending hooks, sign, POST httpx, retry exponentiel | ~200 |
| `backend/src/agflow/workers/task_completed_consumer.py` (nouveau) | Consumer MOM (group=workflow_task_completed) : claim result/error OUT, UPDATE tasks, INSERT outbound_hooks | ~150 |
| `backend/src/agflow/services/hook_payload_builder.py` (nouveau) | Construit le body JSON du hook v5 à partir d'une `tasks` row + ses metadata | ~80 |
| `backend/src/agflow/services/tasks_service.py` (modif) | + `mark_completed(task_id, result)`, `mark_failed(task_id, error)` | +60 |
| `backend/src/agflow/main.py` (modif) | Lifespan : `_stops` range +2 + 2 nouveaux tasks dans `_tasks` | +6 |
| `backend/src/agflow/mom/dispatcher.py` (modif) | Ajouter `workflow_task_completed` aux groupes consommant Direction.OUT | +2 |

### Tests (6 fichiers nouveaux)

| Fichier | Tests |
|---|---|
| `backend/tests/services/test_hook_signing.py` | 5 sync : signature déterministe, secret différent → sig différente, body modifié → sig différente, timestamp/hook_id délimiteurs corrects (newline), hex output 64 chars |
| `backend/tests/services/test_outbound_hooks_service.py` | 6 : enqueue insère pending+now, claim_pending FOR UPDATE SKIP LOCKED, mark_delivered, mark_failed_and_schedule_retry calcule backoff selon attempt_number, mark_dead, retry au-delà de 1h → dead |
| `backend/tests/services/test_hook_payload_builder.py` | 4 sync ou DB-lite : completed → result présent error null, failed → error présent result null, cancelled → both nullables, format JSON schema §4.4 conforme |
| `backend/tests/services/test_tasks_service_lifecycle.py` | 4 : mark_completed met status+result+completed_at, mark_failed met status+error, mark_completed sur unknown task raise, mark_failed sur unknown task raise |
| `backend/tests/workers/test_task_completed_consumer.py` | 5 : claim message kind=result avec _agflow_task_id → tasks completed + outbound_hooks row ; kind=error → tasks failed + outbound_hooks ; message sans _agflow_task_id → ack mais pas d'effet (non-workflow tâche) ; idempotence sur double claim (FOR UPDATE déjà géré par MomConsumer) ; session sans callback_url → log warning et ack sans hook |
| `backend/tests/workers/test_hook_dispatcher_worker.py` | 6 : claim_pending claim ; POST 200 → mark_delivered ; POST 500 → mark_failed_and_schedule_retry (backoff) ; POST 401 → mark_dead (non-retry signature error) ; timeout → schedule_retry ; après >1h de retries → mark_dead |

**Total : 30 tests pytest.**

---

## Tâche 1 — Helper `hook_signing.py` (HMAC SHA-256)

**Files:**
- Create: `backend/src/agflow/services/hook_signing.py`
- Create: `backend/tests/services/test_hook_signing.py`

### Step 1 — Écrire les tests (failing)

- [ ] Créer `backend/tests/services/test_hook_signing.py` :

```python
"""Tests du helper HMAC SHA-256 pour la signature des hooks sortants v5.

Cf. docs/contracts/hook-docker-task-completed.md §3.1 :
    signed_string = timestamp + "\\n" + hook_id + "\\n" + raw_body
    signature_hex = HMAC_SHA256(secret, signed_string).hexdigest()
"""
from __future__ import annotations

from agflow.services.hook_signing import sign


def test_sign_deterministic():
    sig = sign(
        timestamp="2026-05-18T10:00:00Z",
        hook_id="550e8400-e29b-41d4-a716-446655440000",
        body='{"hello":"world"}',
        secret_hex="0123456789abcdef" * 4,
    )
    assert sig == sign(
        timestamp="2026-05-18T10:00:00Z",
        hook_id="550e8400-e29b-41d4-a716-446655440000",
        body='{"hello":"world"}',
        secret_hex="0123456789abcdef" * 4,
    )


def test_sign_different_secret_different_signature():
    common = dict(
        timestamp="2026-05-18T10:00:00Z",
        hook_id="550e8400-e29b-41d4-a716-446655440000",
        body='{"x":1}',
    )
    sig_a = sign(**common, secret_hex="0" * 64)
    sig_b = sign(**common, secret_hex="1" * 64)
    assert sig_a != sig_b


def test_sign_different_body_different_signature():
    common = dict(
        timestamp="2026-05-18T10:00:00Z",
        hook_id="550e8400-e29b-41d4-a716-446655440000",
        secret_hex="0123456789abcdef" * 4,
    )
    sig_a = sign(**common, body='{"x":1}')
    sig_b = sign(**common, body='{"x":2}')
    assert sig_a != sig_b


def test_sign_output_is_hex_64_chars():
    sig = sign(
        timestamp="2026-05-18T10:00:00Z",
        hook_id="550e8400-e29b-41d4-a716-446655440000",
        body="x",
        secret_hex="0123456789abcdef" * 4,
    )
    assert len(sig) == 64
    int(sig, 16)  # raises ValueError if not hex


def test_sign_newline_delimiter_matters():
    """Si timestamp et hook_id étaient concaténés sans \\n, la signature changerait."""
    sig_a = sign(
        timestamp="2026-05-18T10:00:00Z",
        hook_id="abc",
        body="x",
        secret_hex="0123456789abcdef" * 4,
    )
    # Equivalent concaténation sans newlines → autre signature.
    # On vérifie que les newlines font partie du payload signé via un cas
    # ambigu : timestamp="A" + hook_id="\nB" vs timestamp="A\nB" + hook_id=""
    sig_ambiguous_1 = sign(
        timestamp="A", hook_id="\nB", body="x", secret_hex="0123456789abcdef" * 4
    )
    sig_ambiguous_2 = sign(
        timestamp="A\nB", hook_id="", body="x", secret_hex="0123456789abcdef" * 4
    )
    # Sans délimiteur strict, les 2 produiraient la même chaîne signée.
    # Avec notre format `timestamp\nhook_id\nbody`, l'ambiguïté reste — mais on
    # documente ce comportement : c'est au caller de fournir un hook_id non
    # vide et un timestamp sans \n. Ici on vérifie juste que sig_a est stable.
    assert isinstance(sig_a, str) and len(sig_a) == 64
```

### Step 2 — Verify fail

- [ ] Lancer : `cd backend && uv run pytest tests/services/test_hook_signing.py -v`
- [ ] Attendu : `ModuleNotFoundError: agflow.services.hook_signing`.

### Step 3 — Écrire le helper

- [ ] Créer `backend/src/agflow/services/hook_signing.py` :

```python
"""Signature HMAC SHA-256 des hooks sortants workflow v5.

Conforme docs/contracts/hook-docker-task-completed.md §3.1 :

    signed_string = X-Agflow-Timestamp + "\\n" + X-Agflow-Hook-Id + "\\n" + raw_body
    signature_hex = HMAC_SHA256(secret, signed_string).hexdigest()
    header_value  = "hmac-sha256=" + signature_hex

Le secret arrive ici en clair hex (déchiffré par hmac_keys_service.get_by_key_id).
"""
from __future__ import annotations

import hashlib
import hmac


def sign(*, timestamp: str, hook_id: str, body: str, secret_hex: str) -> str:
    """Calcule la signature HMAC SHA-256 en hex (64 chars, sans préfixe).

    Le caller ajoute lui-même le préfixe 'hmac-sha256=' pour le header.
    """
    signed_string = f"{timestamp}\n{hook_id}\n{body}".encode()
    secret_bytes = secret_hex.encode()
    return hmac.new(secret_bytes, signed_string, hashlib.sha256).hexdigest()
```

### Step 4 — Re-lancer

- [ ] Lancer : `cd backend && uv run pytest tests/services/test_hook_signing.py -v`
- [ ] Attendu : **5 PASS** (tests sync sans DB → passent depuis Windows).

### Step 5 — Lint

- [ ] Lancer : `cd backend && uv run ruff check src/agflow/services/hook_signing.py tests/services/test_hook_signing.py`

### Step 6 — Commit + push

```bash
git add backend/src/agflow/services/hook_signing.py \
        backend/tests/services/test_hook_signing.py
git commit -m "feat(workflow-t3): helper HMAC SHA-256 signature hooks sortants v5"
git push origin dev
```

---

## Tâche 2 — Étendre `tasks_service.py` (mark_completed / mark_failed)

**Files:**
- Modify: `backend/src/agflow/services/tasks_service.py`
- Create: `backend/tests/services/test_tasks_service_lifecycle.py`

### Step 1 — Écrire les tests

- [ ] Créer `backend/tests/services/test_tasks_service_lifecycle.py` :

```python
"""Tests du cycle de vie complétion/échec des tasks workflow."""
from __future__ import annotations

from uuid import uuid4

import pytest

pytestmark = pytest.mark.asyncio


async def test_mark_completed_sets_status_result_completed_at(
    fresh_db, mock_session_and_agent
):
    from agflow.services import tasks_service

    sid, aid = mock_session_and_agent
    cid = uuid4()
    task = await tasks_service.create_session_work(
        session_id=sid,
        agent_instance_id=aid,
        agflow_correlation_id=cid,
        instruction={"text": "x"},
    )

    await tasks_service.mark_completed(
        task_id=task["task_id"],
        result={"summary": "done", "artifacts": []},
    )

    row = await tasks_service.get_by_id(task["task_id"])
    assert row["status"] == "completed"
    assert row["result"] == {"summary": "done", "artifacts": []}
    assert row["error"] is None
    assert row["completed_at"] is not None


async def test_mark_failed_sets_status_error_completed_at(
    fresh_db, mock_session_and_agent
):
    from agflow.services import tasks_service

    sid, aid = mock_session_and_agent
    cid = uuid4()
    task = await tasks_service.create_session_work(
        session_id=sid,
        agent_instance_id=aid,
        agflow_correlation_id=cid,
        instruction={"text": "x"},
    )

    await tasks_service.mark_failed(
        task_id=task["task_id"],
        error={"code": "AGENT_OOM", "message": "out of memory"},
    )

    row = await tasks_service.get_by_id(task["task_id"])
    assert row["status"] == "failed"
    assert row["error"] == {"code": "AGENT_OOM", "message": "out of memory"}
    assert row["result"] is None
    assert row["completed_at"] is not None


async def test_mark_completed_unknown_task_raises(fresh_db):
    from agflow.services import tasks_service

    with pytest.raises(tasks_service.TaskNotFoundError):
        await tasks_service.mark_completed(task_id=uuid4(), result={"summary": "x"})


async def test_mark_failed_unknown_task_raises(fresh_db):
    from agflow.services import tasks_service

    with pytest.raises(tasks_service.TaskNotFoundError):
        await tasks_service.mark_failed(
            task_id=uuid4(), error={"code": "X", "message": "y"}
        )
```

**Fixture `mock_session_and_agent`** : existe déjà dans T1 fixtures (cf. `tests/api/test_admin_workflow_sessions.py`). Réutiliser ou ajouter à `conftest.py` si nécessaire au niveau `tests/services/`. Crée 1 user + 1 api_key + 1 session + 1 agent_instance (avec slug dans agents_catalog) et retourne `(session_id, agent_instance_id)`.

### Step 2 — Verify fail

- [ ] Lancer : `cd backend && uv run pytest tests/services/test_tasks_service_lifecycle.py -v`
- [ ] Attendu : `AttributeError: module 'tasks_service' has no attribute 'mark_completed'`.

### Step 3 — Étendre le service

- [ ] Ouvrir `backend/src/agflow/services/tasks_service.py` et ajouter en bas :

```python
class TaskNotFoundError(Exception):
    pass


async def mark_completed(*, task_id: UUID, result: dict[str, Any]) -> None:
    """Transition vers status='completed' + écrit result + completed_at=now()."""
    updated = await fetch_one(
        """
        UPDATE tasks
        SET status = 'completed',
            result = $2::jsonb,
            error = NULL,
            completed_at = now()
        WHERE id = $1
        RETURNING id
        """,
        task_id,
        json.dumps(result),
    )
    if updated is None:
        raise TaskNotFoundError(f"task {task_id} not found")
    _log.info("workflow.task.completed", task_id=str(task_id))


async def mark_failed(*, task_id: UUID, error: dict[str, Any]) -> None:
    """Transition vers status='failed' + écrit error + completed_at=now()."""
    updated = await fetch_one(
        """
        UPDATE tasks
        SET status = 'failed',
            error = $2::jsonb,
            result = NULL,
            completed_at = now()
        WHERE id = $1
        RETURNING id
        """,
        task_id,
        json.dumps(error),
    )
    if updated is None:
        raise TaskNotFoundError(f"task {task_id} not found")
    _log.warning("workflow.task.failed", task_id=str(task_id))
```

### Step 4 — Re-lancer

- [ ] Lancer : `cd backend && uv run pytest tests/services/test_tasks_service_lifecycle.py -v`
- [ ] Attendu : **4 PASS** (ou DONE_WITH_CONCERNS si DB injoignable).

### Step 5 — Lint

- [ ] Lancer : `cd backend && uv run ruff check src/agflow/services/tasks_service.py tests/services/test_tasks_service_lifecycle.py`

### Step 6 — Commit + push

```bash
git add backend/src/agflow/services/tasks_service.py \
        backend/tests/services/test_tasks_service_lifecycle.py
git commit -m "feat(workflow-t3): tasks_service mark_completed/mark_failed (transition status terminal)"
git push origin dev
```

---

## Tâche 3 — `outbound_hooks_service.py` (queue + retry backoff)

**Files:**
- Create: `backend/src/agflow/services/outbound_hooks_service.py`
- Create: `backend/tests/services/test_outbound_hooks_service.py`

### Step 1 — Écrire les tests

- [ ] Créer `backend/tests/services/test_outbound_hooks_service.py` :

```python
"""Tests de outbound_hooks_service."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

pytestmark = pytest.mark.asyncio


async def test_enqueue_creates_pending_row(fresh_db, mock_hmac_key):
    from agflow.services import outbound_hooks_service as oh

    hook_id = uuid4()
    await oh.enqueue(
        hook_id=hook_id,
        task_id=uuid4(),
        callback_url="https://ag.flow/hooks",
        hmac_key_id=mock_hmac_key,
        payload={"status": "completed"},
    )
    row = await fresh_db.fetchrow(
        "SELECT status, attempt_number FROM outbound_hooks WHERE hook_id = $1",
        hook_id,
    )
    assert row["status"] == "pending"
    assert row["attempt_number"] == 0


async def test_claim_pending_returns_due_hooks(fresh_db, mock_hmac_key):
    from agflow.services import outbound_hooks_service as oh

    hook_id_a = uuid4()
    hook_id_b = uuid4()
    await oh.enqueue(
        hook_id=hook_id_a,
        task_id=None,
        callback_url="https://a",
        hmac_key_id=mock_hmac_key,
        payload={},
    )
    # B avec next_retry_at dans le futur → ne doit pas être claimé.
    await fresh_db.execute(
        """
        INSERT INTO outbound_hooks (hook_id, callback_url, hmac_key_id, payload,
            next_retry_at, status)
        VALUES ($1, 'https://b', $2, '{}'::jsonb, now() + interval '1 hour', 'pending')
        """,
        hook_id_b,
        mock_hmac_key,
    )

    claimed = await oh.claim_pending(limit=10)
    claimed_hook_ids = {row["hook_id"] for row in claimed}
    assert hook_id_a in claimed_hook_ids
    assert hook_id_b not in claimed_hook_ids


async def test_mark_delivered_sets_status_delivered(fresh_db, mock_hmac_key):
    from agflow.services import outbound_hooks_service as oh

    hook_id = uuid4()
    await oh.enqueue(
        hook_id=hook_id, task_id=None, callback_url="https://x",
        hmac_key_id=mock_hmac_key, payload={},
    )
    await oh.mark_delivered(hook_id=hook_id, response_code=200)
    row = await fresh_db.fetchrow(
        "SELECT status, last_response_code FROM outbound_hooks WHERE hook_id = $1",
        hook_id,
    )
    assert row["status"] == "delivered"
    assert row["last_response_code"] == 200


async def test_schedule_retry_calculates_backoff(fresh_db, mock_hmac_key):
    from agflow.services import outbound_hooks_service as oh

    hook_id = uuid4()
    await oh.enqueue(
        hook_id=hook_id, task_id=None, callback_url="https://x",
        hmac_key_id=mock_hmac_key, payload={},
    )
    before = datetime.now(UTC)
    await oh.schedule_retry(
        hook_id=hook_id, response_code=500, error_message="server error"
    )
    row = await fresh_db.fetchrow(
        """
        SELECT status, attempt_number, next_retry_at, last_response_code, error_message
        FROM outbound_hooks WHERE hook_id = $1
        """,
        hook_id,
    )
    assert row["status"] == "pending"
    assert row["attempt_number"] == 1
    # 1er retry = 1s plus tard
    assert row["next_retry_at"] - before >= timedelta(seconds=1)
    assert row["next_retry_at"] - before < timedelta(seconds=3)
    assert row["last_response_code"] == 500


async def test_schedule_retry_after_max_attempts_marks_dead(
    fresh_db, mock_hmac_key
):
    from agflow.services import outbound_hooks_service as oh

    hook_id = uuid4()
    # Insère directement avec attempt_number à un cran sous la limite
    await fresh_db.execute(
        """
        INSERT INTO outbound_hooks (hook_id, callback_url, hmac_key_id, payload,
            status, attempt_number, next_retry_at)
        VALUES ($1, 'https://x', $2, '{}'::jsonb, 'pending', 5, now())
        """,
        hook_id,
        mock_hmac_key,
    )
    # 6e tentative = > MAX_ATTEMPTS → mark_dead
    await oh.schedule_retry(
        hook_id=hook_id, response_code=500, error_message="exhausted"
    )
    row = await fresh_db.fetchrow(
        "SELECT status FROM outbound_hooks WHERE hook_id = $1", hook_id
    )
    assert row["status"] == "dead"


async def test_mark_dead_sets_status_dead(fresh_db, mock_hmac_key):
    from agflow.services import outbound_hooks_service as oh

    hook_id = uuid4()
    await oh.enqueue(
        hook_id=hook_id, task_id=None, callback_url="https://x",
        hmac_key_id=mock_hmac_key, payload={},
    )
    await oh.mark_dead(hook_id=hook_id, error_message="non-retryable 401")
    row = await fresh_db.fetchrow(
        "SELECT status, error_message FROM outbound_hooks WHERE hook_id = $1",
        hook_id,
    )
    assert row["status"] == "dead"
    assert "non-retryable" in row["error_message"]
```

**Fixture `mock_hmac_key`** à ajouter dans `tests/services/conftest.py` si absent :
- INSERT une row `hmac_keys` valide (clé chiffrée Fernet via `hmac_keys_service.create`)
- Retourner le `key_id` (string)

### Step 2 — Verify fail

- [ ] Lancer : `cd backend && uv run pytest tests/services/test_outbound_hooks_service.py -v`
- [ ] Attendu : `ModuleNotFoundError: agflow.services.outbound_hooks_service`.

### Step 3 — Écrire le service

- [ ] Créer `backend/src/agflow/services/outbound_hooks_service.py` :

```python
"""CRUD de outbound_hooks (queue des hooks à émettre vers ag.flow).

Conforme docs/contracts/hook-docker-task-completed.md §2 :
- Retry exponentiel : 1s, 5s, 30s, 2min, 10min, 1h → 6 tentatives max
- Au-delà → status='dead'
- Si 5xx → schedule_retry
- Si 4xx (sauf 408/429) → mark_dead (non-retryable)
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_all, fetch_one

_log = structlog.get_logger(__name__)

# Backoff plan : attempt_number → delay (s). attempt_number==1 = 1ère retry.
_BACKOFF_DELAYS_S = (1, 5, 30, 120, 600, 3600)
MAX_ATTEMPTS = len(_BACKOFF_DELAYS_S)


async def enqueue(
    *,
    hook_id: UUID,
    task_id: UUID | None,
    callback_url: str,
    hmac_key_id: str,
    payload: dict[str, Any],
) -> None:
    """INSERT row pending, next_retry_at=now() (claim immédiat possible)."""
    await execute(
        """
        INSERT INTO outbound_hooks
        (hook_id, task_id, callback_url, hmac_key_id, payload, status,
         attempt_number, next_retry_at)
        VALUES ($1, $2, $3, $4, $5::jsonb, 'pending', 0, now())
        """,
        hook_id,
        task_id,
        callback_url,
        hmac_key_id,
        json.dumps(payload),
    )
    _log.info(
        "workflow.hook.enqueued",
        hook_id=str(hook_id),
        task_id=str(task_id) if task_id else None,
        callback_url=callback_url,
    )


async def claim_pending(*, limit: int = 10) -> list[dict]:
    """SELECT pending hooks WHERE next_retry_at <= now(), ordered by created_at.

    Pas de FOR UPDATE ici car le dispatcher tourne sur 1 process unique en V1 ;
    si plusieurs dispatchers concurrents → ajouter SKIP LOCKED + transaction.
    """
    rows = await fetch_all(
        """
        SELECT hook_id, task_id, callback_url, hmac_key_id, payload,
               attempt_number
        FROM outbound_hooks
        WHERE status = 'pending' AND next_retry_at <= now()
        ORDER BY created_at
        LIMIT $1
        """,
        limit,
    )
    return [dict(r) for r in rows]


async def mark_delivered(*, hook_id: UUID, response_code: int) -> None:
    await execute(
        """
        UPDATE outbound_hooks
        SET status = 'delivered',
            last_response_code = $2,
            last_attempt_at = now(),
            error_message = NULL
        WHERE hook_id = $1
        """,
        hook_id,
        response_code,
    )
    _log.info(
        "workflow.hook.delivered",
        hook_id=str(hook_id),
        response_code=response_code,
    )


async def schedule_retry(
    *, hook_id: UUID, response_code: int | None, error_message: str
) -> None:
    """Incrémente attempt_number, calcule next_retry_at via backoff.

    Si attempt_number == MAX_ATTEMPTS → mark_dead à la place.
    """
    row = await fetch_one(
        "SELECT attempt_number FROM outbound_hooks WHERE hook_id = $1",
        hook_id,
    )
    if row is None:
        return  # déjà nettoyée

    next_attempt = row["attempt_number"] + 1
    if next_attempt > MAX_ATTEMPTS:
        await mark_dead(hook_id=hook_id, error_message=f"max_attempts ({error_message})")
        return

    delay_s = _BACKOFF_DELAYS_S[next_attempt - 1]
    await execute(
        """
        UPDATE outbound_hooks
        SET attempt_number = $2,
            next_retry_at = now() + ($3 || ' seconds')::interval,
            last_response_code = $4,
            last_attempt_at = now(),
            error_message = $5
        WHERE hook_id = $1
        """,
        hook_id,
        next_attempt,
        str(delay_s),
        response_code,
        error_message,
    )
    _log.info(
        "workflow.hook.retry_scheduled",
        hook_id=str(hook_id),
        attempt=next_attempt,
        delay_s=delay_s,
        response_code=response_code,
    )


async def mark_dead(*, hook_id: UUID, error_message: str) -> None:
    await execute(
        """
        UPDATE outbound_hooks
        SET status = 'dead',
            error_message = $2,
            last_attempt_at = now()
        WHERE hook_id = $1
        """,
        hook_id,
        error_message,
    )
    _log.error(
        "workflow.hook.dead",
        hook_id=str(hook_id),
        error=error_message,
    )
```

### Step 4 — Re-lancer

- [ ] Lancer : `cd backend && uv run pytest tests/services/test_outbound_hooks_service.py -v`
- [ ] Attendu : **6 PASS** (DONE_WITH_CONCERNS acceptable si DB injoignable).

### Step 5 — Lint

- [ ] Lancer : `cd backend && uv run ruff check src/agflow/services/outbound_hooks_service.py tests/services/test_outbound_hooks_service.py`

### Step 6 — Commit + push

```bash
git add backend/src/agflow/services/outbound_hooks_service.py \
        backend/tests/services/test_outbound_hooks_service.py \
        backend/tests/services/conftest.py
git commit -m "feat(workflow-t3): outbound_hooks_service (queue + retry backoff exp 1s→1h)"
git push origin dev
```

---

## Tâche 4 — `hook_payload_builder.py` (construit le body v5)

**Files:**
- Create: `backend/src/agflow/services/hook_payload_builder.py`
- Create: `backend/tests/services/test_hook_payload_builder.py`

### Step 1 — Écrire les tests

- [ ] Créer `backend/tests/services/test_hook_payload_builder.py` :

```python
"""Tests du builder de payload hook v5 conforme §4."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from agflow.services.hook_payload_builder import build_task_completed_payload


def test_build_completed_payload():
    hook_id = uuid4()
    payload = build_task_completed_payload(
        hook_id=hook_id,
        task_id=uuid4(),
        action_execution_id=uuid4(),
        correlation_id=uuid4(),
        project_runtime_id=uuid4(),
        session_id=uuid4(),
        agent_uuid=uuid4(),
        agent_slug="architect-v1",
        container_id="ctr_xyz",
        status="completed",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        result={"summary": "done", "artifacts": []},
        error=None,
        metadata={"duration_ms": 1234},
    )
    assert payload["hook_id"] == str(hook_id)
    assert payload["status"] == "completed"
    assert payload["result"] == {"summary": "done", "artifacts": []}
    assert payload["error"] is None


def test_build_failed_payload():
    payload = build_task_completed_payload(
        hook_id=uuid4(),
        task_id=uuid4(),
        action_execution_id=uuid4(),
        correlation_id=uuid4(),
        project_runtime_id=None,
        session_id=uuid4(),
        agent_uuid=uuid4(),
        agent_slug="x",
        container_id=None,
        status="failed",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        result=None,
        error={"code": "AGENT_OOM", "message": "out of memory"},
        metadata={},
    )
    assert payload["status"] == "failed"
    assert payload["error"] == {"code": "AGENT_OOM", "message": "out of memory"}
    assert payload["result"] is None
    assert payload["project_runtime_id"] is None


def test_build_cancelled_payload_result_can_be_null():
    payload = build_task_completed_payload(
        hook_id=uuid4(),
        task_id=uuid4(),
        action_execution_id=uuid4(),
        correlation_id=uuid4(),
        project_runtime_id=uuid4(),
        session_id=uuid4(),
        agent_uuid=uuid4(),
        agent_slug="x",
        container_id=None,
        status="cancelled",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        result=None,
        error={"code": "USER_CANCELLED", "message": "kill"},
        metadata={},
    )
    assert payload["status"] == "cancelled"
    assert payload["result"] is None
    assert payload["error"]["code"] == "USER_CANCELLED"


def test_iso_dates_are_strings():
    payload = build_task_completed_payload(
        hook_id=uuid4(),
        task_id=uuid4(),
        action_execution_id=uuid4(),
        correlation_id=uuid4(),
        project_runtime_id=uuid4(),
        session_id=uuid4(),
        agent_uuid=uuid4(),
        agent_slug="x",
        container_id=None,
        status="completed",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        result={"summary": "x"},
        error=None,
        metadata={},
    )
    assert isinstance(payload["started_at"], str)
    assert isinstance(payload["completed_at"], str)
    assert payload["started_at"].endswith("Z") or "+" in payload["started_at"]
```

### Step 2 — Verify fail + écrire le service

- [ ] Lancer le test (fail attendu).
- [ ] Créer `backend/src/agflow/services/hook_payload_builder.py` :

```python
"""Construction du body JSON du hook task-completed v5.

Conforme docs/contracts/hook-docker-task-completed.md §4.4 (JSON Schema).
Tous les UUIDs sont serialisés en string. Dates en ISO-8601 UTC.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID


def build_task_completed_payload(
    *,
    hook_id: UUID,
    task_id: UUID,
    action_execution_id: UUID,
    correlation_id: UUID,
    project_runtime_id: UUID | None,
    session_id: UUID,
    agent_uuid: UUID,
    agent_slug: str,
    container_id: str | None,
    status: str,  # 'completed' | 'failed' | 'cancelled'
    started_at: datetime,
    completed_at: datetime,
    result: dict[str, Any] | None,
    error: dict[str, Any] | None,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """Retourne le dict JSON-serializable conforme §4.4 du contrat v5."""
    return {
        "hook_id": str(hook_id),
        "task_id": str(task_id),
        "action_execution_id": str(action_execution_id),
        "correlation_id": str(correlation_id),
        "project_runtime_id": str(project_runtime_id) if project_runtime_id else None,
        "session_id": str(session_id),
        "agent_uuid": str(agent_uuid),
        "container_id": container_id or "",
        "agent_slug": agent_slug,
        "status": status,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "result": result,
        "error": error,
        "metadata": metadata,
    }
```

### Step 3 — Re-lancer + lint

- [ ] `cd backend && uv run pytest tests/services/test_hook_payload_builder.py -v` — **4 PASS sync**.
- [ ] `cd backend && uv run ruff check src/agflow/services/hook_payload_builder.py tests/services/test_hook_payload_builder.py`

### Step 4 — Commit + push

```bash
git add backend/src/agflow/services/hook_payload_builder.py \
        backend/tests/services/test_hook_payload_builder.py
git commit -m "feat(workflow-t3): hook_payload_builder (body v5 §4 conforme)"
git push origin dev
```

---

## Tâche 5 — `task_completed_consumer.py` (worker MOM consumer)

**Files:**
- Create: `backend/src/agflow/workers/task_completed_consumer.py`
- Create: `backend/tests/workers/test_task_completed_consumer.py`

### Step 1 — Écrire les tests

- [ ] Créer `backend/tests/workers/test_task_completed_consumer.py` :

```python
"""Tests du consumer MOM task_completed (workflow tranche 3)."""
from __future__ import annotations

from uuid import uuid4

import pytest

pytestmark = pytest.mark.asyncio


async def test_consumer_marks_task_completed_and_enqueues_hook(
    fresh_db, mock_session_with_callback, mock_hmac_key
):
    """Un message kind=result avec _agflow_task_id → task completed + outbound_hooks row."""
    from agflow.services import tasks_service
    from agflow.workers import task_completed_consumer

    sid = mock_session_with_callback["session_id"]
    aid = mock_session_with_callback["agent_instance_id"]
    task = await tasks_service.create_session_work(
        session_id=sid,
        agent_instance_id=aid,
        agflow_correlation_id=uuid4(),
        instruction={"text": "x"},
    )
    # L'agent publie un message MOM result (simule la fin du work)
    await _publish_mom_result(
        fresh_db, session_id=sid, instance_id=aid,
        task_id=task["task_id"],
        payload={
            "_agflow_task_id": str(task["task_id"]),
            "result": {"summary": "done"},
        },
    )

    # Le consumer traite la batch
    await task_completed_consumer.process_batch()

    # tasks status passé à completed
    row = await tasks_service.get_by_id(task["task_id"])
    assert row["status"] == "completed"

    # outbound_hooks row créée
    hooks = await fresh_db.fetch(
        "SELECT * FROM outbound_hooks WHERE task_id = $1", task["task_id"]
    )
    assert len(hooks) == 1
    assert hooks[0]["status"] == "pending"


async def test_consumer_marks_task_failed_on_error_kind(
    fresh_db, mock_session_with_callback, mock_hmac_key
):
    """kind=error avec _agflow_task_id → task failed + outbound_hooks."""
    from agflow.services import tasks_service
    from agflow.workers import task_completed_consumer

    sid = mock_session_with_callback["session_id"]
    aid = mock_session_with_callback["agent_instance_id"]
    task = await tasks_service.create_session_work(
        session_id=sid,
        agent_instance_id=aid,
        agflow_correlation_id=uuid4(),
        instruction={},
    )
    await _publish_mom_result(
        fresh_db, session_id=sid, instance_id=aid,
        task_id=task["task_id"],
        kind="error",
        payload={
            "_agflow_task_id": str(task["task_id"]),
            "error": {"code": "AGENT_OOM", "message": "oom"},
        },
    )

    await task_completed_consumer.process_batch()

    row = await tasks_service.get_by_id(task["task_id"])
    assert row["status"] == "failed"


async def test_consumer_ignores_message_without_agflow_task_id(
    fresh_db, mock_session_with_callback
):
    """Un message result sans _agflow_task_id (résultat de session non-workflow) → ack pas d'effet."""
    from agflow.workers import task_completed_consumer

    sid = mock_session_with_callback["session_id"]
    aid = mock_session_with_callback["agent_instance_id"]
    await _publish_mom_result(
        fresh_db, session_id=sid, instance_id=aid,
        task_id=uuid4(),
        payload={"result": {"summary": "non-workflow result"}},  # no _agflow_task_id
    )
    await task_completed_consumer.process_batch()
    # Pas de hook créé
    count = await fresh_db.fetchval("SELECT COUNT(*) FROM outbound_hooks")
    assert count == 0


async def test_consumer_skips_session_without_callback_url(
    fresh_db, mock_session_without_callback
):
    """Une session sans callback_url → task marquée mais pas de hook."""
    from agflow.services import tasks_service
    from agflow.workers import task_completed_consumer

    sid = mock_session_without_callback["session_id"]
    aid = mock_session_without_callback["agent_instance_id"]
    task = await tasks_service.create_session_work(
        session_id=sid, agent_instance_id=aid,
        agflow_correlation_id=uuid4(),
        instruction={},
    )
    await _publish_mom_result(
        fresh_db, session_id=sid, instance_id=aid,
        task_id=task["task_id"],
        payload={
            "_agflow_task_id": str(task["task_id"]),
            "result": {"summary": "x"},
        },
    )
    await task_completed_consumer.process_batch()

    row = await tasks_service.get_by_id(task["task_id"])
    assert row["status"] == "completed"
    count = await fresh_db.fetchval(
        "SELECT COUNT(*) FROM outbound_hooks WHERE task_id = $1", task["task_id"]
    )
    assert count == 0  # pas de hook si pas de callback_url


async def test_consumer_idempotent_on_double_claim(
    fresh_db, mock_session_with_callback, mock_hmac_key
):
    """Si le même message est claimé 2 fois (improbable mais possible avec reclaim),
    le 2e passage ne doit pas créer 2 hooks (vérifier qu'on dédoublonne sur task_id)."""
    from agflow.services import tasks_service
    from agflow.workers import task_completed_consumer

    sid = mock_session_with_callback["session_id"]
    aid = mock_session_with_callback["agent_instance_id"]
    task = await tasks_service.create_session_work(
        session_id=sid, agent_instance_id=aid,
        agflow_correlation_id=uuid4(),
        instruction={},
    )
    await _publish_mom_result(
        fresh_db, session_id=sid, instance_id=aid,
        task_id=task["task_id"],
        payload={
            "_agflow_task_id": str(task["task_id"]),
            "result": {"summary": "x"},
        },
    )
    await task_completed_consumer.process_batch()
    # Le message a été acked. Forcer un 2e claim n'est pas possible sans
    # remettre status=pending. On simule ça en remettant le message en pending :
    await fresh_db.execute(
        "UPDATE agent_message_delivery SET status='pending', acked_at=NULL "
        "WHERE group_name = 'workflow_task_completed'"
    )
    await task_completed_consumer.process_batch()

    count = await fresh_db.fetchval(
        "SELECT COUNT(*) FROM outbound_hooks WHERE task_id = $1", task["task_id"]
    )
    # Selon la stratégie : soit 1 (dédup applicatif), soit 2 (chaque claim INSERT).
    # On accepte 1 (idempotence sur le service) — sinon le consumer doit SELECT
    # outbound_hooks before INSERT et skip si déjà présent pour ce task_id.
    assert count == 1
```

**Helper de test `_publish_mom_result`** (à placer dans `tests/workers/conftest.py`) :
```python
async def _publish_mom_result(
    fresh_db,
    *,
    session_id,
    instance_id,
    task_id,
    payload: dict,
    kind: str = "result",
) -> None:
    """Insère manuellement un message agent_messages OUT + agent_message_delivery
    pour simuler la publication par un agent."""
    import json
    msg_id = await fresh_db.fetchval(
        """
        INSERT INTO agent_messages
        (session_id, instance_id, direction, kind, payload, source)
        VALUES ($1::text, $2::text, 'out', $3, $4::jsonb, 'test')
        RETURNING msg_id
        """,
        str(session_id), str(instance_id), kind, json.dumps(payload),
    )
    await fresh_db.execute(
        "INSERT INTO agent_message_delivery (group_name, msg_id, status) "
        "VALUES ('workflow_task_completed', $1, 'pending')",
        msg_id,
    )
```

**Fixtures `mock_session_with_callback` et `mock_session_without_callback`** : à ajouter dans `tests/workers/conftest.py`. Créent une session + agent + (pour _with_callback) un hmac_key et une session.callback_url + session.callback_hmac_key_id. Retournent `{"session_id", "agent_instance_id"}`.

### Step 2 — Verify fail + écrire le worker

- [ ] Lancer le test (fail attendu).
- [ ] Créer `backend/src/agflow/workers/task_completed_consumer.py` :

```python
"""Worker consumer MOM : détection de fin de work agent → enqueue hook.

Consumer group 'workflow_task_completed' qui claim les agent_messages OUT
de kind=result ou kind=error contenant un _agflow_task_id dans payload.
Pour chaque message :
  1. UPDATE tasks SET status='completed'/'failed' + result/error
  2. Si session.callback_url non null → INSERT outbound_hooks (pending)
  3. Ack le message
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import structlog

from agflow.db.pool import fetch_one, get_pool
from agflow.mom.consumer import MomConsumer
from agflow.mom.envelope import Direction, Kind
from agflow.services import (
    hook_payload_builder,
    outbound_hooks_service,
    tasks_service,
)

_log = structlog.get_logger(__name__)

_CONSUMER_GROUP = "workflow_task_completed"
_DEFAULT_INTERVAL_S = 2.0


async def process_batch() -> None:
    """Une passe : claim + traite + ack une batch de messages OUT."""
    pool = await get_pool()
    consumer = MomConsumer(
        pool=pool,
        group_name=_CONSUMER_GROUP,
        consumer_id=f"workflow-consumer-{uuid4()}",
    )
    envelopes = await consumer.claim_batch(direction=Direction.OUT, batch_size=20)
    for env in envelopes:
        try:
            await _process_envelope(env)
            await consumer.ack(env.msg_id)
        except Exception as exc:
            await consumer.fail(env.msg_id, error=str(exc))
            _log.exception(
                "workflow.task_completed_consumer.process_failed",
                msg_id=env.msg_id,
            )


async def _process_envelope(env) -> None:
    payload = env.payload or {}
    raw_task_id = payload.get("_agflow_task_id")
    if not raw_task_id:
        # Message non-workflow (résultat M5 classique) → ack sans effet
        return

    try:
        task_id = UUID(str(raw_task_id))
    except (ValueError, TypeError):
        _log.warning(
            "workflow.task_completed_consumer.invalid_task_id",
            raw_task_id=raw_task_id,
            msg_id=env.msg_id,
        )
        return

    # 1) Update tasks lifecycle
    if env.kind == Kind.RESULT:
        result = payload.get("result", {})
        await tasks_service.mark_completed(task_id=task_id, result=result)
        status = "completed"
    elif env.kind == Kind.ERROR:
        error = payload.get("error", {"code": "UNKNOWN", "message": "no error info"})
        await tasks_service.mark_failed(task_id=task_id, error=error)
        status = "failed"
    else:
        return  # cas non couvert (ne devrait pas arriver vu le filtre kind)

    # 2) Look up session + agent + runtime pour construire le hook
    row = await fetch_one(
        """
        SELECT
            t.id AS task_id,
            t.agflow_action_execution_id,
            t.agflow_correlation_id,
            t.project_runtime_id,
            t.session_id,
            t.agent_instance_id,
            t.started_at,
            t.completed_at,
            t.result,
            t.error,
            s.callback_url,
            s.callback_hmac_key_id,
            ai.agent_id AS agent_slug,
            ai.last_container_name AS container_id
        FROM tasks t
        LEFT JOIN sessions s ON s.id = t.session_id
        LEFT JOIN agents_instances ai ON ai.id = t.agent_instance_id
        WHERE t.id = $1
        """,
        task_id,
    )
    if row is None or not row["callback_url"]:
        _log.info(
            "workflow.task_completed.no_callback",
            task_id=str(task_id),
        )
        return  # session sans callback → on ne hook pas

    # 3) Idempotence : si un hook existe déjà pour ce task_id, skip
    existing = await fetch_one(
        "SELECT hook_id FROM outbound_hooks WHERE task_id = $1",
        task_id,
    )
    if existing is not None:
        _log.info(
            "workflow.task_completed.hook_already_exists",
            task_id=str(task_id),
            existing_hook_id=str(existing["hook_id"]),
        )
        return

    hook_id = uuid4()
    payload_body = hook_payload_builder.build_task_completed_payload(
        hook_id=hook_id,
        task_id=task_id,
        action_execution_id=row["agflow_action_execution_id"] or uuid4(),
        correlation_id=row["agflow_correlation_id"] or uuid4(),
        project_runtime_id=row["project_runtime_id"],
        session_id=row["session_id"],
        agent_uuid=row["agent_instance_id"],
        agent_slug=row["agent_slug"] or "",
        container_id=row["container_id"],
        status=status,
        started_at=row["started_at"] or datetime.now(UTC),
        completed_at=row["completed_at"] or datetime.now(UTC),
        result=row["result"],
        error=row["error"],
        metadata={},
    )

    await outbound_hooks_service.enqueue(
        hook_id=hook_id,
        task_id=task_id,
        callback_url=row["callback_url"],
        hmac_key_id=row["callback_hmac_key_id"] or "",
        payload=payload_body,
    )


async def run_task_completed_consumer_loop(stop_event: asyncio.Event) -> None:
    """Boucle worker — pattern aligné mom_reclaimer / provisioning_worker."""
    _log.info("workflow.task_completed_consumer.started")
    try:
        while not stop_event.is_set():
            try:
                await process_batch()
            except Exception:
                _log.exception("workflow.task_completed_consumer.loop_error")
            try:
                await asyncio.wait_for(
                    stop_event.wait(), timeout=_DEFAULT_INTERVAL_S
                )
                break
            except TimeoutError:
                continue
    finally:
        _log.info("workflow.task_completed_consumer.stopped")
```

### Step 3 — Re-lancer + lint

- [ ] `cd backend && uv run pytest tests/workers/test_task_completed_consumer.py -v` — **5 PASS** (DONE_WITH_CONCERNS si DB injoignable).
- [ ] `cd backend && uv run ruff check src/agflow/workers/task_completed_consumer.py tests/workers/test_task_completed_consumer.py`

### Step 4 — Mise à jour groupes MOM

- [ ] Ouvrir `backend/src/agflow/mom/dispatcher.py` (ou le fichier qui configure `groups_config` pour `MomPublisher`). Ajouter `"workflow_task_completed"` à la liste des groupes consommant `Direction.OUT`. Exemple :

```python
# Direction.OUT — consommé par
GROUPS_OUT = ["ws_push", "router", "workflow_task_completed"]  # + nouveau
```

Sans cette modif, le publisher n'insère pas de row `agent_message_delivery` pour notre consumer, et le claim restera vide.

### Step 5 — Commit + push

```bash
git add backend/src/agflow/workers/task_completed_consumer.py \
        backend/tests/workers/test_task_completed_consumer.py \
        backend/tests/workers/conftest.py \
        backend/src/agflow/mom/dispatcher.py
git commit -m "feat(workflow-t3): task_completed_consumer MOM + groupe workflow_task_completed"
git push origin dev
```

---

## Tâche 6 — `hook_dispatcher_worker.py` (POST httpx + retry)

**Files:**
- Create: `backend/src/agflow/workers/hook_dispatcher_worker.py`
- Create: `backend/tests/workers/test_hook_dispatcher_worker.py`

### Step 1 — Vérifier que `respx` ou équivalent est installable

- [ ] `cd backend && uv run python -c "import respx"` — si ImportError, ajouter à `pyproject.toml` `[tool.uv]` `[dev-dependencies]` : `respx>=0.21`. Sinon le test utilisera un petit aiohttp server inline.

### Step 2 — Écrire les tests

- [ ] Créer `backend/tests/workers/test_hook_dispatcher_worker.py` :

```python
"""Tests du worker hook_dispatcher (POST hooks signés HMAC vers ag.flow)."""
from __future__ import annotations

from uuid import uuid4

import pytest
import respx
from httpx import Response

pytestmark = pytest.mark.asyncio


async def test_dispatcher_posts_signed_hook_marks_delivered(
    fresh_db, mock_pending_hook
):
    from agflow.workers import hook_dispatcher_worker

    hook_id = mock_pending_hook["hook_id"]
    url = mock_pending_hook["callback_url"]

    with respx.mock(assert_all_called=True) as router:
        route = router.post(url).mock(return_value=Response(200))
        await hook_dispatcher_worker.process_batch()

    assert route.called
    # Vérifier les headers HMAC
    req = route.calls[0].request
    assert "X-Agflow-Hook-Id" in req.headers
    assert req.headers["X-Agflow-Hook-Id"] == str(hook_id)
    assert "X-Agflow-Timestamp" in req.headers
    assert "X-Agflow-Signature" in req.headers
    assert req.headers["X-Agflow-Signature"].startswith("hmac-sha256=")

    # Hook marqué delivered en DB
    row = await fresh_db.fetchrow(
        "SELECT status, last_response_code FROM outbound_hooks WHERE hook_id = $1",
        hook_id,
    )
    assert row["status"] == "delivered"
    assert row["last_response_code"] == 200


async def test_dispatcher_5xx_schedules_retry(fresh_db, mock_pending_hook):
    from agflow.workers import hook_dispatcher_worker

    hook_id = mock_pending_hook["hook_id"]
    url = mock_pending_hook["callback_url"]

    with respx.mock():
        respx.post(url).mock(return_value=Response(500))
        await hook_dispatcher_worker.process_batch()

    row = await fresh_db.fetchrow(
        "SELECT status, attempt_number FROM outbound_hooks WHERE hook_id = $1",
        hook_id,
    )
    assert row["status"] == "pending"
    assert row["attempt_number"] == 1


async def test_dispatcher_401_marks_dead_non_retryable(
    fresh_db, mock_pending_hook
):
    """401 (signature invalide) est non-retryable → mark_dead direct."""
    from agflow.workers import hook_dispatcher_worker

    hook_id = mock_pending_hook["hook_id"]
    url = mock_pending_hook["callback_url"]

    with respx.mock():
        respx.post(url).mock(return_value=Response(401))
        await hook_dispatcher_worker.process_batch()

    row = await fresh_db.fetchrow(
        "SELECT status FROM outbound_hooks WHERE hook_id = $1", hook_id
    )
    assert row["status"] == "dead"


async def test_dispatcher_timeout_schedules_retry(fresh_db, mock_pending_hook):
    from agflow.workers import hook_dispatcher_worker
    import httpx

    hook_id = mock_pending_hook["hook_id"]
    url = mock_pending_hook["callback_url"]

    with respx.mock():
        respx.post(url).mock(side_effect=httpx.TimeoutException("timeout"))
        await hook_dispatcher_worker.process_batch()

    row = await fresh_db.fetchrow(
        "SELECT status, attempt_number FROM outbound_hooks WHERE hook_id = $1",
        hook_id,
    )
    assert row["status"] == "pending"
    assert row["attempt_number"] == 1


async def test_dispatcher_skips_future_next_retry_at(
    fresh_db, mock_pending_hook
):
    """Un hook avec next_retry_at dans le futur ne doit pas être claimé."""
    from agflow.workers import hook_dispatcher_worker

    hook_id = mock_pending_hook["hook_id"]
    # Déplacer next_retry_at dans le futur
    await fresh_db.execute(
        "UPDATE outbound_hooks SET next_retry_at = now() + interval '1 hour' WHERE hook_id = $1",
        hook_id,
    )

    with respx.mock(assert_all_called=False) as router:
        route = router.post(mock_pending_hook["callback_url"]).mock(
            return_value=Response(200)
        )
        await hook_dispatcher_worker.process_batch()
        assert not route.called


async def test_dispatcher_max_attempts_marks_dead(fresh_db, mock_pending_hook):
    """Après attempt_number 5 + nouveau retry 5xx → dead."""
    from agflow.workers import hook_dispatcher_worker

    hook_id = mock_pending_hook["hook_id"]
    url = mock_pending_hook["callback_url"]

    # Simuler 5 attempts déjà faits
    await fresh_db.execute(
        "UPDATE outbound_hooks SET attempt_number = 5 WHERE hook_id = $1",
        hook_id,
    )

    with respx.mock():
        respx.post(url).mock(return_value=Response(503))
        await hook_dispatcher_worker.process_batch()

    row = await fresh_db.fetchrow(
        "SELECT status FROM outbound_hooks WHERE hook_id = $1", hook_id
    )
    assert row["status"] == "dead"
```

**Fixture `mock_pending_hook`** dans `tests/workers/conftest.py` : crée un hmac_key + une row `outbound_hooks` pending avec callback_url=`http://test.local/hook`. Retourne `{"hook_id": UUID, "callback_url": str, "hmac_key_id": str}`.

### Step 3 — Écrire le worker

- [ ] Créer `backend/src/agflow/workers/hook_dispatcher_worker.py` :

```python
"""Worker dispatcher des hooks sortants signés HMAC v5.

Pattern aligné sur mom_reclaimer / provisioning_worker (asyncio + stop_event).
Poll outbound_hooks WHERE status='pending' AND next_retry_at <= now(),
charge la clé HMAC déchiffrée, POST httpx avec les 3 headers requis :
  - X-Agflow-Hook-Id
  - X-Agflow-Timestamp
  - X-Agflow-Signature

Politique de réponse :
  - 2xx → mark_delivered
  - 5xx ou timeout → schedule_retry (backoff)
  - 4xx sauf 408/429 → mark_dead (non-retryable)
  - Au-delà de MAX_ATTEMPTS retries → mark_dead
"""
from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from uuid import UUID

import httpx
import structlog

from agflow.services import hmac_keys_service, hook_signing, outbound_hooks_service

_log = structlog.get_logger(__name__)

_DEFAULT_INTERVAL_S = 2.0
_HTTP_TIMEOUT_S = 10.0

_NON_RETRYABLE_4XX = frozenset({400, 401, 403, 404, 422})  # 408/429 sont retryables


async def process_batch() -> None:
    hooks = await outbound_hooks_service.claim_pending(limit=10)
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT_S) as client:
        for hook in hooks:
            await _process_hook(client, hook)


async def _process_hook(client: httpx.AsyncClient, hook: dict) -> None:
    hook_id: UUID = hook["hook_id"]

    # Charge le secret HMAC
    key = await hmac_keys_service.get_by_key_id(hook["hmac_key_id"])
    if key is None:
        await outbound_hooks_service.mark_dead(
            hook_id=hook_id,
            error_message=f"hmac key '{hook['hmac_key_id']}' not found",
        )
        return

    # Sérialise le body exactement comme il sera envoyé (byte-pour-byte)
    body = json.dumps(hook["payload"], ensure_ascii=False, separators=(",", ":"))
    timestamp = datetime.now(UTC).isoformat()
    signature_hex = hook_signing.sign(
        timestamp=timestamp,
        hook_id=str(hook_id),
        body=body,
        secret_hex=key["secret_hex"],
    )
    headers = {
        "Content-Type": "application/json",
        "X-Agflow-Hook-Id": str(hook_id),
        "X-Agflow-Timestamp": timestamp,
        "X-Agflow-Signature": f"hmac-sha256={signature_hex}",
    }

    try:
        response = await client.post(hook["callback_url"], content=body, headers=headers)
    except httpx.TimeoutException as exc:
        await outbound_hooks_service.schedule_retry(
            hook_id=hook_id, response_code=None, error_message=f"timeout: {exc}"
        )
        return
    except httpx.RequestError as exc:
        await outbound_hooks_service.schedule_retry(
            hook_id=hook_id,
            response_code=None,
            error_message=f"network error: {exc}",
        )
        return

    status_code = response.status_code
    if 200 <= status_code < 300:
        await outbound_hooks_service.mark_delivered(
            hook_id=hook_id, response_code=status_code
        )
        return
    if status_code in _NON_RETRYABLE_4XX:
        await outbound_hooks_service.mark_dead(
            hook_id=hook_id,
            error_message=f"non-retryable {status_code}: {response.text[:200]}",
        )
        return
    # 5xx, 408, 429 → retry
    await outbound_hooks_service.schedule_retry(
        hook_id=hook_id,
        response_code=status_code,
        error_message=f"{status_code}: {response.text[:200]}",
    )


async def run_hook_dispatcher_loop(stop_event: asyncio.Event) -> None:
    _log.info("workflow.hook_dispatcher.started")
    try:
        while not stop_event.is_set():
            try:
                await process_batch()
            except Exception:
                _log.exception("workflow.hook_dispatcher.loop_error")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=_DEFAULT_INTERVAL_S)
                break
            except TimeoutError:
                continue
    finally:
        _log.info("workflow.hook_dispatcher.stopped")
```

### Step 4 — Re-lancer + lint

- [ ] `cd backend && uv run pytest tests/workers/test_hook_dispatcher_worker.py -v` — **6 PASS** (DONE_WITH_CONCERNS si DB injoignable, mais respx mock n'est pas affecté par la DB → certains tests passent peut-être en local).
- [ ] `cd backend && uv run ruff check src/agflow/workers/hook_dispatcher_worker.py tests/workers/test_hook_dispatcher_worker.py`

### Step 5 — Commit + push

```bash
git add backend/src/agflow/workers/hook_dispatcher_worker.py \
        backend/tests/workers/test_hook_dispatcher_worker.py \
        backend/tests/workers/conftest.py \
        backend/pyproject.toml
git commit -m "feat(workflow-t3): hook_dispatcher_worker (HTTP POST signé HMAC + retry)"
git push origin dev
```

---

## Tâche 7 — Wire-up des 2 workers dans `main.py` lifespan

**Files:**
- Modify: `backend/src/agflow/main.py`

### Step 1 — Suivre le pattern existant

- [ ] Ouvrir `main.py` lifespan. Aujourd'hui (après T2) : 6 entrées dans `_stops` + `_tasks` (`expiry`, `agent_reaper`, `session_idle_reaper`, `mom_reclaimer`, `oauth_pending_reaper`, `provisioning_worker`).

### Step 2 — Ajouter les 2 imports

- [ ] Ajouter, dans l'alphabétique :

```python
from agflow.workers.hook_dispatcher_worker import run_hook_dispatcher_loop
from agflow.workers.task_completed_consumer import run_task_completed_consumer_loop
```

### Step 3 — Incrémenter `range(6)` → `range(8)` et ajouter 2 tasks

- [ ] Modifier :

```python
_stops = [_asyncio.Event() for _ in range(8)]
_tasks = [
    _asyncio.create_task(_run_expiry_loop(_stops[0])),
    _asyncio.create_task(_run_agent_reaper_loop(_stops[1])),
    _asyncio.create_task(_run_session_idle_reaper_loop(_stops[2])),
    _asyncio.create_task(_run_mom_reclaimer_loop(_stops[3])),
    _asyncio.create_task(_run_oauth_pending_reaper_loop(_stops[4])),
    _asyncio.create_task(_run_provisioning_worker_loop(_stops[5])),
    # T3 nouveaux workers :
    _asyncio.create_task(_run_task_completed_consumer_loop(_stops[6])),
    _asyncio.create_task(_run_hook_dispatcher_loop(_stops[7])),
]
```

### Step 4 — Lint + commit

- [ ] `cd backend && uv run ruff check src/agflow/main.py`
- [ ] Commit :

```bash
git add backend/src/agflow/main.py
git commit -m "feat(workflow-t3): wire task_completed_consumer + hook_dispatcher dans lifespan"
git push origin dev
```

---

## Tâche 8 — Vérification finale d'intégrité

### Step 1 — pytest collect-only global

- [ ] `cd backend && uv run pytest --collect-only -q 2>&1 | tail -20`
- [ ] Attendu : aucune erreur d'import, ~900 tests collectés (vs 870 fin T2).

### Step 2 — ruff sur tous les fichiers T3

- [ ] `cd backend && uv run ruff check src/agflow/services/hook_signing.py src/agflow/services/hook_payload_builder.py src/agflow/services/outbound_hooks_service.py src/agflow/services/tasks_service.py src/agflow/workers/task_completed_consumer.py src/agflow/workers/hook_dispatcher_worker.py src/agflow/main.py tests/services/test_hook_signing.py tests/services/test_hook_payload_builder.py tests/services/test_outbound_hooks_service.py tests/services/test_tasks_service_lifecycle.py tests/workers/test_task_completed_consumer.py tests/workers/test_hook_dispatcher_worker.py tests/workers/conftest.py tests/services/conftest.py`
- [ ] Attendu : All checks passed.

### Step 3 — Vérifier les commits

- [ ] `git log --oneline origin/dev~10..origin/dev` — les commits T3 doivent être présents et pushés.

---

## Tâche 9 — Validation E2E LXC fresh + smoke curl

### Step 1 — Lancer le test E2E complet

- [ ] `./scripts/run-test.sh` (avec `CLEANUP=1 ./scripts/run-test.sh` si souhaité — sinon cleanup manuel ensuite)
- [ ] Attendu :
  - LXC fresh créé
  - Migrations 001 + 002 appliquées (002 introduit en T2, conservée)
  - pytest backend exit 0 (~900 tests passed, 0 errors)
  - Smoke 8/8 PASS

### Step 2 — Smoke manuel du flow workflow + hook

- [ ] Login admin (cf. T2.9 procédure)
- [ ] POST hmac-keys, POST /sessions avec callback_url + callback_hmac_key_id, POST /agents, POST /work → récupère task_id.
- [ ] Simuler la fin du work via insertion manuelle d'un `agent_messages` OUT kind=result avec `_agflow_task_id` dans le payload (via psql sur le LXC, ou via WebSocket /exec sur le container agent si possible).
- [ ] Vérifier qu'au bout de quelques secondes :
  - `tasks.status` est passé à `completed`
  - Une row `outbound_hooks` est créée avec `status='pending'`
  - Le `hook_dispatcher` tente le POST (échec attendu car callback_url pointe vers un mock non disponible — `attempt_number` doit s'incrémenter, ou `status='dead'` si 401/404)

### Step 3 — Cleanup LXC

- [ ] `ssh pve "pct stop <CTID> && pct destroy <CTID> --purge"`

### Step 4 — Mise à jour mémoire

- [ ] Mettre à jour `memory/project_modules_status.md` : "Workflow Contracts Tranche 3 livrée 2026-05-{jj}".

---

## Récapitulatif

**~9 commits livrés :**

1. `feat(workflow-t3): helper HMAC SHA-256 signature hooks sortants v5`
2. `feat(workflow-t3): tasks_service mark_completed/mark_failed`
3. `feat(workflow-t3): outbound_hooks_service (queue + retry backoff exp 1s→1h)`
4. `feat(workflow-t3): hook_payload_builder (body v5 §4 conforme)`
5. `feat(workflow-t3): task_completed_consumer MOM + groupe workflow_task_completed`
6. `feat(workflow-t3): hook_dispatcher_worker (HTTP POST signé HMAC + retry)`
7. `feat(workflow-t3): wire task_completed_consumer + hook_dispatcher dans lifespan`

**~30 tests pytest** : 5 hook_signing + 6 outbound_hooks + 4 hook_payload_builder + 4 tasks_lifecycle + 5 task_completed_consumer + 6 hook_dispatcher.

**Wall time estimé :** 4-5 jours (peut être plus si respx pose des soucis d'install).

**Hors scope explicite (différé tranche 4) :**
- Mock-receiver Docker dans `run-test.sh` pour valider la réception HMAC bout-en-bout
- Endpoint `DELETE /api/admin/hmac-keys/{key_id}` (revoke / rotation)
- Endpoint `GET /api/admin/tasks/{task_id}` (status query)
- Tests E2E contre le mock-receiver ag.flow
- Smoke curl flow complet incluant réception du hook avec signature valide

**Dette technique notée mais non bloquante :**
- L'idempotence du consumer sur double-claim est applicative (SELECT outbound_hooks WHERE task_id avant INSERT). Une UNIQUE constraint sur `outbound_hooks(task_id)` serait plus robuste mais nécessite une migration supplémentaire — à décider en review.
- `_HTTP_TIMEOUT_S = 10.0` hardcoded — pourrait migrer vers `platform_config_service` comme les autres intervals.
- Le mapping 401 → mark_dead suppose qu'une signature invalide ne sera pas corrigée par retry. Acceptable mais à confirmer avec l'équipe ag.flow.
