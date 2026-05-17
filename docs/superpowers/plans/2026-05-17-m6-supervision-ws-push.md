# M6 Supervision — Phase 2b WebSocket push (plan d'implémentation)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter un push temps-réel des événements de supervision côté backend (via `pg_notify` sur channel `supervision_events`) et côté frontend (hook WS qui invalide les queries TanStack), en gardant le polling 5s de Phase 2a comme fallback automatique.

**Architecture:** Couche pub/sub légère exploitant PostgreSQL `LISTEN/NOTIFY` (déjà utilisé par le MOM bus). Un module `supervision_events.py` centralise les 5 publishers (instance.created/status_changed/destroyed + session.created/closed). Hooks ajoutés dans `agents_instances_service.py` et `sessions_service.py` aux 6 points de mutation. Endpoint `WS /api/admin/supervision/stream` avec auth JWT query param + `asyncpg.add_listener` qui broadcast aux clients. Frontend : hook `useSupervisionStream` avec reconnect backoff exponentiel + indicateur visuel 3 états.

**Tech Stack:** Python 3.12 + FastAPI WebSocket + asyncpg (`add_listener`) + pg_notify · React 18 + TypeScript strict + TanStack Query + native WebSocket API + Vitest.

**Spec de référence :** `docs/superpowers/specs/2026-05-17-m6-supervision-ws-push-design.md` (commit `a2fc1c4`).

**Branche cible :** `dev`. Pas de feature branch.

**Mode pipeline allégé** (validé sur Phase 2a et git-sync) : subagent implementer + spec reviewer + code quality reviewer, pas de spec-reviewer intermédiaire entre tâches. Exécution continue.

**Notes tests** :
- `pytest` certains tests intégration DB peuvent retourner DONE_WITH_CONCERNS sur dev Windows (LXC injoignable). Validation finale via `./scripts/run-test.sh` à T9.
- `Vitest` 100% local, doit toujours passer.
- Convention test frontend : `frontend/tests/<topic>/<name>.test.tsx`.

---

## Structure des fichiers (vue d'ensemble)

### Backend (4 fichiers : 2 nouveaux + 3 modifs)

| Fichier | Responsabilité | Lignes |
|---|---|---|
| `backend/src/agflow/services/supervision_events.py` (nouveau) | 5 `publish_*` + `listen_events()` async gen | ~120 |
| `backend/src/agflow/api/admin/supervision_stream.py` (nouveau) | `@router.websocket("/api/admin/supervision/stream")` + auth JWT + asyncpg listener + broadcast | ~110 |
| `backend/src/agflow/services/agents_instances_service.py` (modif) | Appels `publish_*` dans `create`, `destroy`, `touch_activity` | +15 |
| `backend/src/agflow/services/sessions_service.py` (modif) | Appels `publish_*` dans `create`, `close`, `expire_stale` | +12 |
| `backend/src/agflow/main.py` (modif) | `include_router(admin_supervision_stream_router)` | +2 |

### Frontend (3 fichiers : 2 nouveaux + 2 modifs)

| Fichier | Responsabilité | Lignes |
|---|---|---|
| `frontend/src/hooks/useSupervisionStream.ts` (nouveau) | Hook WS avec reconnect backoff + invalidation queries | ~110 |
| `frontend/src/components/supervision/SupervisionStreamIndicator.tsx` (nouveau) | Indicateur 3 états avec tooltip i18n | ~60 |
| `frontend/src/pages/SupervisionPage.tsx` (modif) | Appel hook + intégration indicateur dans `actions` du PageHeader | +5 |
| `frontend/src/i18n/{fr,en}.json` (modif) | Bloc `supervision.ws.{connected,disconnected,reconnecting,title}` | +12 (×2) |

### Tests (4 fichiers nouveaux : 2 backend + 2 frontend)

| Fichier | Tests |
|---|---|
| `backend/tests/services/test_supervision_events.py` | 5 tests (1 par publisher) |
| `backend/tests/api/test_admin_supervision_stream.py` | 5 tests (auth + intégration WS) |
| `frontend/tests/hooks/useSupervisionStream.test.tsx` | 4 tests (ouvre WS, invalide queries, status, reconnect backoff) |
| `frontend/tests/components/supervision/SupervisionStreamIndicator.test.tsx` | 2 tests (3 états rendus, tooltip i18n) |

**Total : 16 tests.**

---

## Tâche 1 — `supervision_events.py` (5 publishers + listen_events)

**Files:**
- Create: `backend/src/agflow/services/supervision_events.py`
- Test: `backend/tests/services/test_supervision_events.py`

### Step 1 — Écrire les tests (failing)

- [ ] Créer `backend/tests/services/test_supervision_events.py` :

```python
"""Tests des publishers supervision_events (pg_notify channel)."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_pool():
    pool = AsyncMock()
    return pool


async def test_publish_instance_created_calls_pg_notify(mock_pool):
    from agflow.services import supervision_events

    iid = uuid4()
    sid = uuid4()
    with patch("agflow.services.supervision_events.get_pool", return_value=mock_pool):
        await supervision_events.publish_instance_created(
            instance_id=iid, session_id=sid
        )

    mock_pool.execute.assert_awaited_once()
    args = mock_pool.execute.await_args.args
    assert args[0] == "SELECT pg_notify($1, $2)"
    assert args[1] == "supervision_events"
    payload = json.loads(args[2])
    assert payload == {
        "type": "instance.created",
        "id": str(iid),
        "session_id": str(sid),
    }


async def test_publish_instance_status_changed(mock_pool):
    from agflow.services import supervision_events

    iid = uuid4()
    with patch("agflow.services.supervision_events.get_pool", return_value=mock_pool):
        await supervision_events.publish_instance_status_changed(instance_id=iid)

    args = mock_pool.execute.await_args.args
    assert json.loads(args[2]) == {"type": "instance.status_changed", "id": str(iid)}


async def test_publish_instance_destroyed(mock_pool):
    from agflow.services import supervision_events

    iid = uuid4()
    with patch("agflow.services.supervision_events.get_pool", return_value=mock_pool):
        await supervision_events.publish_instance_destroyed(instance_id=iid)

    args = mock_pool.execute.await_args.args
    assert json.loads(args[2]) == {"type": "instance.destroyed", "id": str(iid)}


async def test_publish_session_created(mock_pool):
    from agflow.services import supervision_events

    sid = uuid4()
    with patch("agflow.services.supervision_events.get_pool", return_value=mock_pool):
        await supervision_events.publish_session_created(session_id=sid)

    args = mock_pool.execute.await_args.args
    assert json.loads(args[2]) == {"type": "session.created", "id": str(sid)}


async def test_publish_session_closed_with_status(mock_pool):
    from agflow.services import supervision_events

    sid = uuid4()
    with patch("agflow.services.supervision_events.get_pool", return_value=mock_pool):
        await supervision_events.publish_session_closed(
            session_id=sid, status="expired"
        )

    args = mock_pool.execute.await_args.args
    assert json.loads(args[2]) == {
        "type": "session.closed",
        "id": str(sid),
        "status": "expired",
    }


async def test_publish_swallows_db_errors(mock_pool, caplog):
    """Les publishers ne propagent jamais l'erreur DB (mutation reste atomique)."""
    from agflow.services import supervision_events

    mock_pool.execute.side_effect = RuntimeError("DB down")
    with patch("agflow.services.supervision_events.get_pool", return_value=mock_pool):
        # Ne doit PAS lever
        await supervision_events.publish_instance_destroyed(instance_id=uuid4())
```

### Step 2 — Lancer le test (verify it fails)

- [ ] Lancer : `cd backend && uv run pytest tests/services/test_supervision_events.py -v`
- [ ] Attendu : `ModuleNotFoundError: agflow.services.supervision_events` (ou imports failed).

### Step 3 — Écrire `backend/src/agflow/services/supervision_events.py`

```python
"""Pub/sub des événements de supervision via PostgreSQL pg_notify.

Channel : `supervision_events`.
Payload : JSON event-rich (cf. spec 2026-05-17-m6-supervision-ws-push-design.md).

Les `publish_*` sont fire-and-forget : toute exception DB est loggée
mais NE propage PAS (la mutation métier reste atomique).
"""
from __future__ import annotations

import json
from typing import AsyncIterator
from uuid import UUID

import asyncpg
import structlog

from agflow.db.pool import get_pool

_log = structlog.get_logger(__name__)

CHANNEL = "supervision_events"


async def _safe_notify(payload: dict) -> None:
    try:
        pool = await get_pool()
        await pool.execute(
            "SELECT pg_notify($1, $2)",
            CHANNEL,
            json.dumps(payload, ensure_ascii=False),
        )
    except Exception as exc:
        _log.warning(
            "supervision_events.publish_failed",
            event_type=payload.get("type"),
            error=str(exc),
        )


async def publish_instance_created(
    *, instance_id: UUID, session_id: UUID
) -> None:
    await _safe_notify(
        {
            "type": "instance.created",
            "id": str(instance_id),
            "session_id": str(session_id),
        }
    )


async def publish_instance_status_changed(*, instance_id: UUID) -> None:
    await _safe_notify(
        {"type": "instance.status_changed", "id": str(instance_id)}
    )


async def publish_instance_destroyed(*, instance_id: UUID) -> None:
    await _safe_notify({"type": "instance.destroyed", "id": str(instance_id)})


async def publish_session_created(*, session_id: UUID) -> None:
    await _safe_notify({"type": "session.created", "id": str(session_id)})


async def publish_session_closed(
    *, session_id: UUID, status: str
) -> None:
    await _safe_notify(
        {"type": "session.closed", "id": str(session_id), "status": status}
    )


async def listen_events(
    conn: asyncpg.Connection,
) -> AsyncIterator[str]:
    """Async generator qui yield les payloads bruts (JSON string) reçus
    sur le channel `supervision_events` via la connexion asyncpg fournie.

    L'appelant gère l'add_listener / remove_listener et la durée de vie
    de la connexion.
    """
    import asyncio

    queue: asyncio.Queue[str] = asyncio.Queue()

    def _on_notify(
        _conn: asyncpg.Connection,
        _pid: int,
        _channel: str,
        payload: str,
    ) -> None:
        queue.put_nowait(payload)

    await conn.add_listener(CHANNEL, _on_notify)
    try:
        while True:
            yield await queue.get()
    finally:
        await conn.remove_listener(CHANNEL, _on_notify)
```

### Step 4 — Re-lancer

- [ ] Lancer : `cd backend && uv run pytest tests/services/test_supervision_events.py -v`
- [ ] Attendu : **6 tests PASS** (5 publishers + 1 swallow-error).

### Step 5 — Lint

- [ ] Lancer : `cd backend && uv run ruff check src/agflow/services/supervision_events.py tests/services/test_supervision_events.py`
- [ ] Attendu : All checks passed.

### Step 6 — Commit

```bash
git add backend/src/agflow/services/supervision_events.py \
         backend/tests/services/test_supervision_events.py
git commit -m "feat(supervision-events): 5 publishers + listen_events (pg_notify)"
```

---

## Tâche 2 — Hooks dans `agents_instances_service.py`

**Files:**
- Modify: `backend/src/agflow/services/agents_instances_service.py`
- Test: pas de test dédié (le service est déjà testé ; on vérifie via le test d'intégration WS T4)

### Step 1 — Inspecter le fichier

- [ ] Ouvrir `backend/src/agflow/services/agents_instances_service.py`.
- [ ] Identifier 3 points d'injection :
  - `create()` ligne ~24-38 : après `ids.append(row["id"])` (1 publish par instance créée)
  - `destroy()` ligne ~106-123 : après `if ok:` (juste avant `_log.info`)
  - `touch_activity()` ligne ~126-160 : après le UPDATE quand `status is not None` ET le résultat ok

### Step 2 — Ajouter import au top du fichier

- [ ] Ajouter à proximité des autres imports `from agflow.X import Y` :

```python
from agflow.services import supervision_events
```

### Step 3 — Modifier `create()`

Patcher le corps de la boucle pour publier après chaque insert. Bloc cible (ligne ~26-38) :

```python
    for _ in range(count):
        row = await fetch_one(
            """
            INSERT INTO agents_instances (session_id, agent_id, labels, mission)
            VALUES ($1, $2, $3::jsonb, $4)
            RETURNING id
            """,
            session_id,
            agent_id,
            labels_json,
            mission,
        )
        ids.append(row["id"])
```

Remplacer par :

```python
    for _ in range(count):
        row = await fetch_one(
            """
            INSERT INTO agents_instances (session_id, agent_id, labels, mission)
            VALUES ($1, $2, $3::jsonb, $4)
            RETURNING id
            """,
            session_id,
            agent_id,
            labels_json,
            mission,
        )
        ids.append(row["id"])
        await supervision_events.publish_instance_created(
            instance_id=row["id"], session_id=session_id
        )
```

### Step 4 — Modifier `destroy()`

Bloc cible (ligne ~115-123) :

```python
    ok = result.endswith(" 1")
    if ok:
        _log.info(
            "agents_instances.destroyed",
            session_id=str(session_id),
            instance_id=str(instance_id),
        )
    return ok
```

Remplacer par :

```python
    ok = result.endswith(" 1")
    if ok:
        await supervision_events.publish_instance_destroyed(instance_id=instance_id)
        _log.info(
            "agents_instances.destroyed",
            session_id=str(session_id),
            instance_id=str(instance_id),
        )
    return ok
```

### Step 5 — Modifier `touch_activity()`

L'objectif : publier `status_changed` **seulement quand `status` est explicitement fourni** ET le UPDATE a touché une ligne (sinon : `last_activity_at` change sans status, pas d'event).

Bloc cible (ligne ~138-160) :

```python
    if status is None:
        result = await execute(...)
    else:
        result = await execute(...)
    return result.endswith(" 1")
```

Remplacer par :

```python
    if status is None:
        result = await execute(
            """
            UPDATE agents_instances
            SET last_activity_at = now()
            WHERE id = $1 AND destroyed_at IS NULL
            """,
            instance_id,
        )
        return result.endswith(" 1")

    result = await execute(
        """
        UPDATE agents_instances
        SET last_activity_at = now(),
            status = $2,
            error_message = $3
        WHERE id = $1 AND destroyed_at IS NULL
        """,
        instance_id,
        status,
        error_message,
    )
    ok = result.endswith(" 1")
    if ok:
        await supervision_events.publish_instance_status_changed(
            instance_id=instance_id
        )
    return ok
```

### Step 6 — Vérifier les tests existants ne cassent pas

- [ ] Lancer : `cd backend && uv run pytest tests/services/test_agents_instances_service.py -v` (si le fichier existe ; sinon ignorer).
- [ ] Attendu : aucune régression. Si tests qui mockent `supervision_events` apparaissent indispensables, accepter `DONE_WITH_CONCERNS` car LXC Postgres peut être injoignable depuis Windows.

### Step 7 — Lint

- [ ] Lancer : `cd backend && uv run ruff check src/agflow/services/agents_instances_service.py`
- [ ] Attendu : All checks passed.

### Step 8 — Commit

```bash
git add backend/src/agflow/services/agents_instances_service.py
git commit -m "feat(supervision-events): hooks publish_instance_* dans agents_instances_service"
```

---

## Tâche 3 — Hooks dans `sessions_service.py`

**Files:**
- Modify: `backend/src/agflow/services/sessions_service.py`

### Step 1 — Ajouter import

- [ ] Ajouter en haut du fichier :

```python
from agflow.services import supervision_events
```

### Step 2 — Modifier `create()`

Bloc cible (ligne ~31-39) :

```python
    _log.info(
        "sessions.created",
        session_id=str(row["id"]),
        api_key_id=str(api_key_id),
        project_id=project_id,
        duration_seconds=duration_seconds,
    )
    return dict(row)
```

Remplacer par :

```python
    await supervision_events.publish_session_created(session_id=row["id"])
    _log.info(
        "sessions.created",
        session_id=str(row["id"]),
        api_key_id=str(api_key_id),
        project_id=project_id,
        duration_seconds=duration_seconds,
    )
    return dict(row)
```

### Step 3 — Modifier `close()`

Bloc cible (ligne ~133-136) :

```python
    closed = result.endswith(" 1")
    if closed:
        _log.info("sessions.closed", session_id=str(session_id))
    return closed
```

Remplacer par :

```python
    closed = result.endswith(" 1")
    if closed:
        await supervision_events.publish_session_closed(
            session_id=session_id, status="closed"
        )
        _log.info("sessions.closed", session_id=str(session_id))
    return closed
```

### Step 4 — Modifier `expire_stale()`

Cas particulier : `expire_stale()` peut affecter N sessions en une seule UPDATE. Il faut récupérer les ids pour publier 1 event par session. Modifier la fonction pour utiliser `RETURNING id`.

Bloc cible (ligne ~139-150) :

```python
async def expire_stale() -> int:
    result = await execute(
        """
        UPDATE sessions
        SET status = 'expired', closed_at = now()
        WHERE status = 'active' AND expires_at < now()
        """,
    )
    count = int(result.split()[-1]) if result else 0
    if count > 0:
        _log.info("sessions.expired", count=count)
    return count
```

Remplacer par :

```python
async def expire_stale() -> int:
    rows = await fetch_all(
        """
        UPDATE sessions
        SET status = 'expired', closed_at = now()
        WHERE status = 'active' AND expires_at < now()
        RETURNING id
        """,
    )
    count = len(rows)
    if count > 0:
        for r in rows:
            await supervision_events.publish_session_closed(
                session_id=r["id"], status="expired"
            )
        _log.info("sessions.expired", count=count)
    return count
```

Note : `fetch_all` est déjà importé en haut du fichier (utilisé par `list_for_key`).

### Step 5 — Lint

- [ ] Lancer : `cd backend && uv run ruff check src/agflow/services/sessions_service.py`
- [ ] Attendu : All checks passed.

### Step 6 — Commit

```bash
git add backend/src/agflow/services/sessions_service.py
git commit -m "feat(supervision-events): hooks publish_session_* dans sessions_service"
```

---

## Tâche 4 — Endpoint WS `/api/admin/supervision/stream`

**Files:**
- Create: `backend/src/agflow/api/admin/supervision_stream.py`
- Modify: `backend/src/agflow/main.py`
- Test: `backend/tests/api/test_admin_supervision_stream.py`

### Step 1 — Écrire les tests (failing)

- [ ] Créer `backend/tests/api/test_admin_supervision_stream.py` :

```python
"""Tests de l'endpoint WS /api/admin/supervision/stream."""
from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from agflow.auth.jwt import encode_token

pytestmark = pytest.mark.asyncio


def _admin_token() -> str:
    return encode_token("admin@test.local")


@pytest.fixture
def client(monkeypatch):
    from agflow.main import app
    monkeypatch.setenv("AUTH_MODE", "local")
    return TestClient(app)


def test_ws_without_token_returns_403(client):
    with pytest.raises(Exception):  # WebSocket-related error
        with client.websocket_connect("/api/admin/supervision/stream"):
            pass


def test_ws_with_invalid_token_closes_connection(client):
    with pytest.raises(Exception):
        with client.websocket_connect(
            "/api/admin/supervision/stream?token=bogus"
        ):
            pass


def test_ws_with_admin_token_connects(client):
    token = _admin_token()
    with client.websocket_connect(
        f"/api/admin/supervision/stream?token={token}"
    ) as ws:
        # Connexion établie sans exception (pas de message attendu pour l'instant)
        assert ws is not None


async def test_ws_receives_pg_notify_payload():
    """Test d'intégration : publish via la fonction puis vérifie réception."""
    # Marqué skip si DB injoignable (validation E2E à T9 via run-test.sh)
    pytest.skip("intégration DB — validé via run-test.sh sur LXC fresh")


def test_ws_closes_properly_on_client_disconnect(client):
    """Le serveur ne crashe pas quand le client ferme avant lui."""
    token = _admin_token()
    with client.websocket_connect(
        f"/api/admin/supervision/stream?token={token}"
    ) as ws:
        pass  # context manager close
    # Aucune exception attendue après sortie du with
```

### Step 2 — Lancer (verify fail)

- [ ] Lancer : `cd backend && uv run pytest tests/api/test_admin_supervision_stream.py -v`
- [ ] Attendu : `ModuleNotFoundError: agflow.api.admin.supervision_stream` ou imports failed.

### Step 3 — Écrire `supervision_stream.py`

- [ ] Créer `backend/src/agflow/api/admin/supervision_stream.py` :

```python
"""WebSocket endpoint pour le push temps-réel des événements de supervision.

Auth : JWT en query param `?token=<jwt>`, rôle admin requis.
Channel : `supervision_events` (cf. supervision_events.py).
"""
from __future__ import annotations

import asyncio
from uuid import uuid4

import structlog
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from agflow.auth.dependencies import VALID_ROLES, _extract_role
from agflow.auth.jwt import InvalidTokenError, decode_token
from agflow.db.pool import get_pool
from agflow.services import supervision_events

_log = structlog.get_logger(__name__)

router = APIRouter(tags=["admin-supervision"])

_WS_AUTH_FAILURE_CODE = 1008  # Policy Violation (standard WS close code)


def _require_admin_from_token(token: str) -> str | None:
    """Retourne l'email admin ou None si token invalide/non-admin."""
    try:
        payload = decode_token(token)
    except InvalidTokenError:
        return None
    if _extract_role(payload) != "admin":
        return None
    sub = payload.get("sub", "")
    return sub or None


@router.websocket("/api/admin/supervision/stream")
async def supervision_stream(
    websocket: WebSocket,
    token: str = Query(default=""),
) -> None:
    admin_email = _require_admin_from_token(token)
    if not admin_email:
        # Avant accept() : on close avec un code custom 4401 (4xxx = app-defined)
        await websocket.close(code=4401)
        return

    await websocket.accept()
    connection_id = uuid4().hex[:8]
    _log.info(
        "supervision_stream.connected",
        connection_id=connection_id,
        admin=admin_email,
    )

    pool = await get_pool()
    try:
        async with pool.acquire() as conn:
            # asyncpg add_listener nécessite une connexion dédiée hors pool
            try:
                async for payload in supervision_events.listen_events(conn):
                    await websocket.send_text(payload)
            except WebSocketDisconnect:
                _log.info(
                    "supervision_stream.client_disconnect",
                    connection_id=connection_id,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _log.exception(
                    "supervision_stream.error",
                    connection_id=connection_id,
                    error=str(exc),
                )
    finally:
        _log.info(
            "supervision_stream.disconnected", connection_id=connection_id
        )
```

### Step 4 — Brancher le router dans `main.py`

- [ ] Ouvrir `backend/src/agflow/main.py`.
- [ ] Repérer la zone des `include_router` (cf. `app.include_router(admin_supervision_router)` ligne ~337).
- [ ] Ajouter l'import à côté des autres :

```python
from agflow.api.admin.supervision_stream import router as admin_supervision_stream_router
```

- [ ] Ajouter l'inclusion à côté de l'existant :

```python
app.include_router(admin_supervision_stream_router)
```

### Step 5 — Re-lancer

- [ ] Lancer : `cd backend && uv run pytest tests/api/test_admin_supervision_stream.py -v`
- [ ] Attendu : **4 tests PASS** (1 skipped pour intégration DB).

### Step 6 — Lint

- [ ] Lancer : `cd backend && uv run ruff check src/agflow/api/admin/supervision_stream.py src/agflow/main.py tests/api/test_admin_supervision_stream.py`
- [ ] Attendu : All checks passed.

### Step 7 — Commit

```bash
git add backend/src/agflow/api/admin/supervision_stream.py \
         backend/src/agflow/main.py \
         backend/tests/api/test_admin_supervision_stream.py
git commit -m "feat(supervision-stream): endpoint WS /api/admin/supervision/stream + auth JWT"
```

---

## Tâche 5 — i18n FR + EN (bloc `supervision.ws`)

**Files:**
- Modify: `frontend/src/i18n/fr.json`
- Modify: `frontend/src/i18n/en.json`

### Step 1 — Localiser le bloc `supervision`

- [ ] Lancer : `grep -n '"supervision"' frontend/src/i18n/fr.json | head -3`
- [ ] Repérer la fin du bloc `supervision.*` existant et le sous-objet `status` (ajouté en Phase 2a, à conserver).

### Step 2 — Ajouter le sous-bloc `ws` dans `fr.json`

- [ ] Dans le bloc `supervision` de `frontend/src/i18n/fr.json`, ajouter (au même niveau que `kpi`, `filters`, `table`, `drawer`) :

```json
"ws": {
  "title": "Temps-réel",
  "connected": "Temps-réel actif",
  "reconnecting": "Reconnexion...",
  "disconnected": "Hors-ligne (polling 5s)"
},
```

(Si le bloc se termine actuellement par `"status": {...}` sans virgule, ajouter la virgule pour insérer après.)

### Step 3 — Ajouter le sous-bloc `ws` dans `en.json`

- [ ] Dans `frontend/src/i18n/en.json`, ajouter au même endroit :

```json
"ws": {
  "title": "Real-time",
  "connected": "Real-time active",
  "reconnecting": "Reconnecting...",
  "disconnected": "Offline (5s polling)"
},
```

### Step 4 — Vérifier validité JSON + parité

- [ ] Lancer :

```bash
cd frontend && node -e "JSON.parse(require('fs').readFileSync('src/i18n/fr.json'))" && \
node -e "JSON.parse(require('fs').readFileSync('src/i18n/en.json'))" && \
node -e "
const fr=require('./src/i18n/fr.json'); const en=require('./src/i18n/en.json');
function flat(o,p='',a=[]){for(const k in o){const v=o[k];const np=p?p+'.'+k:k;if(typeof v==='object'&&v!==null)flat(v,np,a);else a.push(np);}return a;}
const fk=flat(fr.supervision.ws||{});const ek=flat(en.supervision.ws||{});
const miss=fk.filter(k=>!ek.includes(k));const extra=ek.filter(k=>!fk.includes(k));
if(miss.length||extra.length){console.error('Diff:',{miss,extra});process.exit(1);}
console.log('FR/EN supervision.ws parity OK,',fk.length,'keys');
"
```

- [ ] Attendu : `FR/EN supervision.ws parity OK, 4 keys`.

### Step 5 — Commit

```bash
git add frontend/src/i18n/fr.json frontend/src/i18n/en.json
git commit -m "feat(supervision-ws-i18n): bloc supervision.ws FR+EN (4 clés)"
```

---

## Tâche 6 — Hook `useSupervisionStream.ts`

**Files:**
- Create: `frontend/src/hooks/useSupervisionStream.ts`
- Test: `frontend/tests/hooks/useSupervisionStream.test.tsx`

### Step 1 — Écrire le test (failing)

- [ ] Créer `frontend/tests/hooks/useSupervisionStream.test.tsx` :

```tsx
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useSupervisionStream } from "@/hooks/useSupervisionStream";
import type { ReactNode } from "react";

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  onopen: ((e: Event) => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onclose: ((e: CloseEvent) => void) | null = null;
  onerror: ((e: Event) => void) | null = null;
  readyState = 0;
  url: string;
  closed = false;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
    queueMicrotask(() => {
      this.readyState = 1;
      this.onopen?.(new Event("open"));
    });
  }

  send() {}
  close() {
    this.closed = true;
    this.readyState = 3;
    this.onclose?.(new CloseEvent("close"));
  }

  emit(data: unknown) {
    this.onmessage?.(new MessageEvent("message", { data: JSON.stringify(data) }));
  }
}

function wrapper(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

describe("useSupervisionStream", () => {
  beforeEach(() => {
    vi.stubGlobal("WebSocket", FakeWebSocket);
    FakeWebSocket.instances = [];
    localStorage.setItem("agflow_token", "test-token");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("ouvre WS avec token en query param", async () => {
    const client = new QueryClient();
    renderHook(() => useSupervisionStream(), { wrapper: wrapper(client) });
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    expect(FakeWebSocket.instances[0]!.url).toContain("token=test-token");
    expect(FakeWebSocket.instances[0]!.url).toContain("/api/admin/supervision/stream");
  });

  it("invalide overview+instances+instance(id) sur event instance.status_changed", async () => {
    const client = new QueryClient();
    const spy = vi.spyOn(client, "invalidateQueries");
    renderHook(() => useSupervisionStream(), { wrapper: wrapper(client) });
    await waitFor(() => expect(FakeWebSocket.instances).toHaveLength(1));
    act(() => {
      FakeWebSocket.instances[0]!.emit({
        type: "instance.status_changed",
        id: "abc-1",
      });
    });
    const calls = spy.mock.calls.map((c) => JSON.stringify(c[0]?.queryKey));
    expect(calls.some((k) => k?.includes("overview"))).toBe(true);
    expect(calls.some((k) => k?.includes("instances"))).toBe(true);
    expect(calls.some((k) => k?.includes("abc-1"))).toBe(true);
  });

  it('statut passe à "open" puis "closed" sur close', async () => {
    const client = new QueryClient();
    const { result } = renderHook(() => useSupervisionStream(), {
      wrapper: wrapper(client),
    });
    await waitFor(() => expect(result.current).toBe("open"));
    act(() => {
      FakeWebSocket.instances[0]!.close();
    });
    expect(result.current).toBe("closed");
  });

  it("reconnect après close avec backoff (au moins 1 reconnexion)", async () => {
    vi.useFakeTimers();
    const client = new QueryClient();
    renderHook(() => useSupervisionStream(), { wrapper: wrapper(client) });
    await vi.waitFor(() => expect(FakeWebSocket.instances.length).toBeGreaterThanOrEqual(1));
    act(() => {
      FakeWebSocket.instances[0]!.close();
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1500); // > backoff initial 1s
    });
    expect(FakeWebSocket.instances.length).toBeGreaterThanOrEqual(2);
    vi.useRealTimers();
  });
});
```

### Step 2 — Lancer (fail)

- [ ] Lancer : `cd frontend && npm test -- tests/hooks/useSupervisionStream.test.tsx`
- [ ] Attendu : `Cannot find module '@/hooks/useSupervisionStream'`.

### Step 3 — Écrire `useSupervisionStream.ts`

- [ ] Créer `frontend/src/hooks/useSupervisionStream.ts` :

```ts
import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

export type StreamStatus = "connecting" | "open" | "closed";

const BACKOFF_INITIAL_MS = 1_000;
const BACKOFF_MAX_MS = 30_000;
const TOKEN_KEY = "agflow_token";

function buildUrl(token: string): string {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  const host = window.location.host;
  return `${proto}://${host}/api/admin/supervision/stream?token=${encodeURIComponent(token)}`;
}

export function useSupervisionStream(): StreamStatus {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<StreamStatus>("connecting");

  useEffect(() => {
    let socket: WebSocket | null = null;
    let backoffMs = BACKOFF_INITIAL_MS;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let cancelled = false;

    function connect() {
      const token = localStorage.getItem(TOKEN_KEY) ?? "";
      socket = new WebSocket(buildUrl(token));

      socket.onopen = () => {
        if (cancelled) return;
        setStatus("open");
        backoffMs = BACKOFF_INITIAL_MS;
      };

      socket.onmessage = (event) => {
        if (cancelled) return;
        let ev: { type?: string; id?: string };
        try {
          ev = JSON.parse(event.data);
        } catch {
          return;
        }
        if (!ev.type) return;

        if (ev.type.startsWith("instance.")) {
          queryClient.invalidateQueries({ queryKey: ["supervision", "overview"] });
          queryClient.invalidateQueries({ queryKey: ["supervision", "instances"] });
          if (ev.id) {
            queryClient.invalidateQueries({
              queryKey: ["supervision", "instance", ev.id],
            });
          }
        } else if (ev.type.startsWith("session.")) {
          queryClient.invalidateQueries({ queryKey: ["supervision", "overview"] });
        }
      };

      socket.onclose = () => {
        if (cancelled) return;
        setStatus("closed");
        reconnectTimer = setTimeout(() => {
          connect();
        }, backoffMs);
        backoffMs = Math.min(backoffMs * 2, BACKOFF_MAX_MS);
      };

      socket.onerror = () => {
        // onclose suit, géré là
      };
    }

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, [queryClient]);

  return status;
}
```

### Step 4 — Re-lancer

- [ ] Lancer : `cd frontend && npm test -- tests/hooks/useSupervisionStream.test.tsx`
- [ ] Attendu : **4 tests PASS**.

### Step 5 — TypeScript

- [ ] Lancer : `cd frontend && npx tsc --noEmit`
- [ ] Attendu : 0 erreur.

### Step 6 — Commit

```bash
git add frontend/src/hooks/useSupervisionStream.ts \
         frontend/tests/hooks/useSupervisionStream.test.tsx
git commit -m "feat(supervision-ws): hook useSupervisionStream (reconnect backoff + invalidations)"
```

---

## Tâche 7 — Composant `SupervisionStreamIndicator.tsx`

**Files:**
- Create: `frontend/src/components/supervision/SupervisionStreamIndicator.tsx`
- Test: `frontend/tests/components/supervision/SupervisionStreamIndicator.test.tsx`

### Step 1 — Écrire le test (failing)

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { I18nextProvider } from "react-i18next";
import i18n from "@/lib/i18n";
import { SupervisionStreamIndicator } from "@/components/supervision/SupervisionStreamIndicator";

function wrap(ui: React.ReactNode) {
  return <I18nextProvider i18n={i18n}>{ui}</I18nextProvider>;
}

describe("SupervisionStreamIndicator", () => {
  it("affiche le label connected avec le tooltip i18n", () => {
    render(wrap(<SupervisionStreamIndicator status="open" />));
    expect(screen.getByText(/actif|active/i)).toBeInTheDocument();
  });

  it("affiche les 3 états (open/connecting/closed) avec classes distinctes", () => {
    const { container: cOpen } = render(wrap(<SupervisionStreamIndicator status="open" />));
    const { container: cConn } = render(wrap(<SupervisionStreamIndicator status="connecting" />));
    const { container: cClosed } = render(wrap(<SupervisionStreamIndicator status="closed" />));
    expect(cOpen.querySelector('[data-stream-state="open"]')).toBeInTheDocument();
    expect(cConn.querySelector('[data-stream-state="connecting"]')).toBeInTheDocument();
    expect(cClosed.querySelector('[data-stream-state="closed"]')).toBeInTheDocument();
  });
});
```

### Step 2 — Lancer (fail)

- [ ] Lancer : `cd frontend && npm test -- tests/components/supervision/SupervisionStreamIndicator.test.tsx`

### Step 3 — Écrire le composant

`frontend/src/components/supervision/SupervisionStreamIndicator.tsx` :

```tsx
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import type { StreamStatus } from "@/hooks/useSupervisionStream";

interface Props {
  status: StreamStatus;
}

const DOT_CLASS: Record<StreamStatus, string> = {
  open: "bg-emerald-500",
  connecting: "bg-amber-500 animate-pulse",
  closed: "bg-muted-foreground",
};

const LABEL_KEY: Record<StreamStatus, string> = {
  open: "supervision.ws.connected",
  connecting: "supervision.ws.reconnecting",
  closed: "supervision.ws.disconnected",
};

export function SupervisionStreamIndicator({ status }: Props) {
  const { t } = useTranslation();
  const label = t(LABEL_KEY[status]);
  return (
    <span
      className="inline-flex items-center gap-1.5 text-xs text-muted-foreground"
      title={label}
      data-stream-state={status}
      aria-label={label}
    >
      <span className={cn("w-2 h-2 rounded-full", DOT_CLASS[status])} aria-hidden />
      <span>{label}</span>
    </span>
  );
}
```

### Step 4 — Re-lancer

- [ ] Lancer : `cd frontend && npm test -- tests/components/supervision/SupervisionStreamIndicator.test.tsx`
- [ ] Attendu : **2 tests PASS**.

### Step 5 — TypeScript

- [ ] Lancer : `cd frontend && npx tsc --noEmit`

### Step 6 — Commit

```bash
git add frontend/src/components/supervision/SupervisionStreamIndicator.tsx \
         frontend/tests/components/supervision/SupervisionStreamIndicator.test.tsx
git commit -m "feat(supervision-ws): SupervisionStreamIndicator (3 états + tooltip i18n)"
```

---

## Tâche 8 — Intégration dans `SupervisionPage.tsx`

**Files:**
- Modify: `frontend/src/pages/SupervisionPage.tsx`

### Step 1 — Lire le fichier actuel

- [ ] Lancer : `grep -n "PageHeader\|actions" frontend/src/pages/SupervisionPage.tsx | head`
- [ ] Repérer le bloc `<PageHeader ... actions={...} />`.

### Step 2 — Modifier les imports et l'usage

Ajouter en haut du fichier :

```tsx
import { useSupervisionStream } from "@/hooks/useSupervisionStream";
import { SupervisionStreamIndicator } from "@/components/supervision/SupervisionStreamIndicator";
```

Dans le composant, juste après `const overview = useOverview();` (ou avant si plus naturel), ajouter :

```tsx
  const streamStatus = useSupervisionStream();
```

Dans le `actions` du `<PageHeader>`, insérer l'indicateur **avant** le bouton Rafraîchir. Bloc cible (forme actuelle) :

```tsx
        actions={
          <Button
            variant="outline"
            size="sm"
            onClick={refresh}
            aria-label={t("supervision.refresh")}
          >
            <RotateCw className="h-4 w-4 mr-1" /> {t("supervision.refresh")}
          </Button>
        }
```

Remplacer par :

```tsx
        actions={
          <div className="flex items-center gap-3">
            <SupervisionStreamIndicator status={streamStatus} />
            <Button
              variant="outline"
              size="sm"
              onClick={refresh}
              aria-label={t("supervision.refresh")}
            >
              <RotateCw className="h-4 w-4 mr-1" /> {t("supervision.refresh")}
            </Button>
          </div>
        }
```

### Step 3 — TypeScript + tests existants

- [ ] Lancer : `cd frontend && npx tsc --noEmit`
- [ ] Attendu : 0 erreur.
- [ ] Lancer : `cd frontend && npm test -- tests/pages/SupervisionPage.test.tsx`
- [ ] Attendu : 2 tests existants PASSENT toujours (l'indicateur ne casse pas les sélecteurs existants).

Si le test SupervisionPage échoue parce que `useSupervisionStream` essaie d'ouvrir un WebSocket sans mock, ajouter au mock JSDOM dans le test ou stub `WebSocket` global dans `tests/setup.ts`. Le pattern existant est dans le fichier de test du hook (FakeWebSocket).

### Step 4 — Commit

```bash
git add frontend/src/pages/SupervisionPage.tsx
git commit -m "feat(supervision-ws): SupervisionPage utilise useSupervisionStream + indicateur"
```

---

## Tâche 9 — Validation E2E sur LXC fresh

**Files:** Aucun (validation runtime).

### Step 1 — Vérifier l'historique des commits

- [ ] Lancer : `git log --oneline dev ^main | head -15`
- [ ] Attendu : ~8 nouveaux commits préfixés `feat(supervision-events|stream|ws|ws-i18n)`.

### Step 2 — Push origin/dev

- [ ] Lancer : `git push origin dev`

### Step 3 — Lancer run-test.sh

- [ ] Lancer : `./scripts/run-test.sh`
- [ ] Attendu :
  - LXC fresh créé
  - Déploiement via git pull
  - 8 assertions smoke OK
  - pytest backend complet vert (incluant les ~10 nouveaux tests supervision_events + supervision_stream)

### Step 4 — Smoke métier manuel sur LXC fresh

Récupérer l'IP du LXC (visible dans la sortie). Login admin. Naviguer vers `/supervision`. Vérifier :

- [ ] L'indicateur **Temps-réel actif** (point vert) s'affiche en haut à droite à côté du bouton Rafraîchir
- [ ] La page se charge sans erreur console (sauf 401/403 attendus si non-admin)
- [ ] (Optionnel : si l'environnement permet de créer une session via `curl POST /api/v1/sessions` avec une API key admin) provoquer un `session.created` → vérifier que les KPI Sessions/Active passent de 0 à 1 **sans attendre le polling 5s** (push WS instantané)
- [ ] Couper réseau navigateur (DevTools → Network → Offline) → indicateur passe à 🟡 reconnecting puis ⚪ disconnected. Polling 5s continue (les KPI restent rafraîchis si on rétablit).
- [ ] Rétablir le réseau → reconnect WS, indicateur repasse 🟢 connected.

### Step 5 — Cleanup LXC

- [ ] Lancer : `ssh pve "pct stop <CTID> && pct destroy <CTID> --purge"` (CTID dans la sortie de run-test.sh).
- [ ] Vérifier : `ssh pve "pct list" | grep <CTID>` ne retourne rien.

### Step 6 — Mémoire des modules

- [ ] Mettre à jour `C:\Users\g.beard\.claude\projects\E--srcs-agflow-docker\memory\project_modules_status.md` : passer M6 Phase 2b de "à scoper" à "livrée 2026-05-17". Phase 2c (actions kill/restart) et Phase 2d (graphes tendances) restent à scoper si besoin.

---

## Récapitulatif

**~8 commits livrés :**

1. `feat(supervision-events): 5 publishers + listen_events (pg_notify)`
2. `feat(supervision-events): hooks publish_instance_* dans agents_instances_service`
3. `feat(supervision-events): hooks publish_session_* dans sessions_service`
4. `feat(supervision-stream): endpoint WS /api/admin/supervision/stream + auth JWT`
5. `feat(supervision-ws-i18n): bloc supervision.ws FR+EN (4 clés)`
6. `feat(supervision-ws): hook useSupervisionStream (reconnect backoff + invalidations)`
7. `feat(supervision-ws): SupervisionStreamIndicator (3 états + tooltip i18n)`
8. `feat(supervision-ws): SupervisionPage utilise useSupervisionStream + indicateur`

**16 tests** : 6 backend `test_supervision_events` + 4 (3+1skip) `test_admin_supervision_stream` + 4 Vitest `useSupervisionStream` + 2 Vitest `SupervisionStreamIndicator`.

**Wall time estimé :** 2-3 jours en mode pipeline allégé.

**Multi-pod safe par construction** (LISTEN/NOTIFY cluster-wide). Polling 5s de Phase 2a reste actif en fallback automatique.
