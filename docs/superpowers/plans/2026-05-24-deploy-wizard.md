# Deploy Wizard — Plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remplacer le bouton "Pousser" monolithique par un wizard 3-onglets (Configuration → Exécution step-by-step avec logs SSE → Déploiement) piloté par une machine à états backend.

**Architecture:** Backend state machine sur `project_deployments` ; chaque script `before` s'exécute en tâche asyncio isolée, publie ses logs dans un bus in-process (asyncio Queue), consommé par un endpoint SSE. L'executor met à jour `accumulated_env` après chaque step. Design API-first : le wizard est un client parmi d'autres.

**Tech Stack:** Python 3.12 + FastAPI + asyncpg + asyncssh + asyncio.Queue (SSE bus) ; React 18 + TanStack Query + EventSource API + shadcn/ui Tabs

---

## Structure des fichiers

**Créer :**
- `backend/migrations/002_deploy_wizard.sql`
- `backend/src/agflow/services/deployment_log_bus.py`
- `backend/src/agflow/services/deployment_executor.py`
- `backend/tests/test_deployment_executor.py`
- `frontend/src/components/projects/DeployWizardDialog.tsx`

**Modifier :**
- `backend/src/agflow/schemas/products.py` — DeploymentStatus étendu, DeploymentSummary enrichi, nouveaux modèles
- `backend/src/agflow/services/project_deployments_service.py` — helpers step management
- `backend/src/agflow/services/ssh_executor.py` — exec streaming
- `backend/src/agflow/api/admin/project_deployments.py` — 4 nouveaux endpoints + generate mis à jour
- `frontend/src/lib/projectsApi.ts` — nouveaux types + méthodes
- `frontend/src/i18n/fr.json` + `en.json`
- `frontend/src/pages/ProjectDetailPage.tsx` — remplace DeployDialog

---

## Task 1 — Migration SQL

**Files:**
- Create: `backend/migrations/002_deploy_wizard.sql`

- [ ] **Step 1 : Écrire la migration**

```sql
-- 002_deploy_wizard.sql
-- Étend project_deployments pour le wizard step-by-step

-- 1. Nouvelles colonnes
ALTER TABLE project_deployments
    ADD COLUMN IF NOT EXISTS current_step_index INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS accumulated_env     JSONB   NOT NULL DEFAULT '{}',
    ADD COLUMN IF NOT EXISTS step_logs           JSONB   NOT NULL DEFAULT '[]';

-- 2. Remplace le CHECK status inline par un CHECK nommé avec tous les états
ALTER TABLE project_deployments
    DROP CONSTRAINT IF EXISTS project_deployments_status_check;

ALTER TABLE project_deployments
    ADD CONSTRAINT project_deployments_status_check
    CHECK (status IN (
        'draft', 'generated',
        'executing_step', 'step_complete', 'step_failed', 'before_complete',
        'deploying', 'deployed', 'failed'
    ));
```

- [ ] **Step 2 : Appliquer la migration**

```powershell
cd backend
uv run python -m agflow.db.migrations
```

Expected : `Applied: 002_deploy_wizard.sql`

- [ ] **Step 3 : Commit**

```bash
git add backend/migrations/002_deploy_wizard.sql
git commit -m "feat(db): migration 002 — deploy wizard columns + statuts étendus"
```

---

## Task 2 — Schemas Python (DeploymentStatus + nouveaux modèles)

**Files:**
- Modify: `backend/src/agflow/schemas/products.py:166-191`

- [ ] **Step 1 : Écrire le test**

Fichier `backend/tests/test_deployment_schemas.py` :

```python
from agflow.schemas.products import DeploymentSummary, ExecuteStepRequest, StepLog
from datetime import datetime
from uuid import uuid4

def test_deployment_summary_has_wizard_fields():
    d = DeploymentSummary(
        id=uuid4(), project_id=uuid4(), user_id=uuid4(),
        status="step_complete", current_step_index=1,
        accumulated_env={"KC_CLIENT_ID": "abc"},
        step_logs=[{"step_index": 0, "lines": ["ok"], "exit_code": 0}],
        generated_secrets={}, nullable_secrets=[],
        generated_data={}, group_servers={},
        created_at=datetime.now(), updated_at=datetime.now(),
    )
    assert d.current_step_index == 1
    assert d.accumulated_env["KC_CLIENT_ID"] == "abc"

def test_execute_step_request_defaults():
    r = ExecuteStepRequest()
    assert r.group_vars == {}

def test_step_log_model():
    s = StepLog(step_index=0, lines=["line1"], exit_code=0)
    assert s.exit_code == 0
```

- [ ] **Step 2 : Vérifier que le test échoue**

```powershell
cd backend; uv run pytest tests/test_deployment_schemas.py -v
```

Expected : FAIL (`ExecuteStepRequest` not found)

- [ ] **Step 3 : Implémenter les changements schemas**

Dans `backend/src/agflow/schemas/products.py`, remplacer à partir de la ligne 166 :

```python
DeploymentStatus = Literal[
    "draft", "generated",
    "executing_step", "step_complete", "step_failed", "before_complete",
    "deploying", "deployed", "failed",
]


class StepLog(BaseModel):
    step_index: int
    lines: list[str] = Field(default_factory=list)
    exit_code: int = -1
    started_at: datetime | None = None
    ended_at: datetime | None = None


class ExecuteStepRequest(BaseModel):
    pass  # état courant lu depuis la DB


class GenerateRequest(BaseModel):
    user_secrets: dict[str, str] = {}
    group_vars: dict[str, str] = {}  # override des valeurs de variables de groupe au moment du generate


class DeploymentCreate(BaseModel):
    project_id: UUID
    group_servers: dict[str, str] = Field(default_factory=dict)


class DeploymentUpdate(BaseModel):
    group_servers: dict[str, str] | None = None


class DeploymentSummary(BaseModel):
    id: UUID
    project_id: UUID
    user_id: UUID
    group_servers: dict[str, str] = Field(default_factory=dict)
    status: DeploymentStatus = "draft"
    current_step_index: int = 0
    accumulated_env: dict[str, Any] = Field(default_factory=dict)
    step_logs: list[StepLog] = Field(default_factory=list)
    generated_compose: str | None = None
    generated_env: str | None = None
    generated_secrets: dict[str, str] = Field(default_factory=dict)
    nullable_secrets: list[str] = Field(default_factory=list)
    generated_data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
```

Note : `GenerateRequest` est déplacé ici depuis `project_deployments.py` (Task 8 supprimera le doublon).

- [ ] **Step 4 : Vérifier le test**

```powershell
cd backend; uv run pytest tests/test_deployment_schemas.py -v
```

Expected : PASS

- [ ] **Step 5 : Commit**

```bash
git add backend/src/agflow/schemas/products.py backend/tests/test_deployment_schemas.py
git commit -m "feat(schemas): DeploymentStatus étendu, StepLog, GenerateRequest.group_vars"
```

---

## Task 3 — project_deployments_service : helpers wizard

**Files:**
- Modify: `backend/src/agflow/services/project_deployments_service.py`

- [ ] **Step 1 : Écrire les tests**

Fichier `backend/tests/test_deployment_service_wizard.py` :

```python
import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4
from agflow.services import project_deployments_service as svc


@pytest.fixture
def mock_deployment():
    dep_id = uuid4()
    return {
        "id": dep_id, "project_id": uuid4(), "user_id": uuid4(),
        "group_servers": {}, "status": "generated",
        "current_step_index": 0,
        "accumulated_env": "{}",
        "step_logs": "[]",
        "generated_compose": None, "generated_env": "KEY=val",
        "generated_secrets": "{}", "nullable_secrets": "[]",
        "generated_data": "{}",
        "created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00",
    }


@pytest.mark.asyncio
async def test_advance_step_index(mock_deployment):
    dep_id = mock_deployment["id"]
    with patch("agflow.services.project_deployments_service.execute", new_callable=AsyncMock) as mock_exec, \
         patch("agflow.services.project_deployments_service.fetch_one", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = {**mock_deployment, "current_step_index": 1, "status": "step_complete"}
        result = await svc.advance_step(dep_id, new_accumulated_env={"K": "v"}, new_log={"step_index": 0, "lines": [], "exit_code": 0}, next_status="step_complete")
        mock_exec.assert_awaited_once()
        assert result.current_step_index == 1


@pytest.mark.asyncio
async def test_reset_step_for_retry(mock_deployment):
    dep_id = mock_deployment["id"]
    with patch("agflow.services.project_deployments_service.execute", new_callable=AsyncMock) as mock_exec, \
         patch("agflow.services.project_deployments_service.fetch_one", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = {**mock_deployment, "status": "executing_step"}
        result = await svc.reset_to_executing(dep_id)
        mock_exec.assert_awaited_once()
```

- [ ] **Step 2 : Vérifier que les tests échouent**

```powershell
cd backend; uv run pytest tests/test_deployment_service_wizard.py -v
```

Expected : FAIL (`advance_step` not found)

- [ ] **Step 3 : Mettre à jour `_COLS` et `_to_summary`**

Dans `project_deployments_service.py`, mettre à jour la ligne `_COLS` :

```python
_COLS = (
    "id, project_id, user_id, group_servers, status, current_step_index, "
    "accumulated_env, step_logs, generated_compose, generated_env, "
    "generated_secrets, nullable_secrets, generated_data, created_at, updated_at"
)
```

Et `_to_summary` :

```python
def _to_summary(row: dict[str, Any]) -> DeploymentSummary:
    gs = row.get("group_servers") or {}
    return DeploymentSummary(
        id=row["id"],
        project_id=row["project_id"],
        user_id=row["user_id"],
        group_servers=gs if isinstance(gs, dict) else json.loads(gs or "{}"),
        status=row.get("status") or "draft",
        current_step_index=row.get("current_step_index") or 0,
        accumulated_env=_json_field(row, "accumulated_env", {}),
        step_logs=[StepLog(**s) for s in _json_field(row, "step_logs", [])],
        generated_compose=row.get("generated_compose"),
        generated_env=row.get("generated_env"),
        generated_secrets=_json_field(row, "generated_secrets", {}),
        nullable_secrets=_json_field(row, "nullable_secrets", []),
        generated_data=_json_field(row, "generated_data", {}),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
```

Ajouter en tête de fichier l'import `StepLog` depuis les schemas, et un helper `_json_field` :

```python
from agflow.schemas.products import DeploymentSummary, DeploymentStatus, StepLog

def _json_field(row: dict, key: str, default: Any) -> Any:
    v = row.get(key)
    if v is None:
        return default
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v)
    except (json.JSONDecodeError, TypeError):
        return default
```

- [ ] **Step 4 : Ajouter les helpers wizard**

À la fin de `project_deployments_service.py` :

```python
async def set_status(deployment_id: UUID, new_status: DeploymentStatus) -> None:
    await execute(
        "UPDATE project_deployments SET status = $1, updated_at = now() WHERE id = $2",
        new_status, deployment_id,
    )


async def advance_step(
    deployment_id: UUID,
    new_accumulated_env: dict[str, Any],
    new_log: dict[str, Any],
    next_status: DeploymentStatus,
) -> DeploymentSummary:
    """Ajoute un step_log, met à jour accumulated_env, avance current_step_index."""
    current = await get_by_id(deployment_id)
    logs = [s.model_dump() for s in current.step_logs] + [new_log]
    merged_env = {**current.accumulated_env, **new_accumulated_env}
    await execute(
        """
        UPDATE project_deployments
        SET status = $1,
            current_step_index = current_step_index + 1,
            accumulated_env = $2::jsonb,
            step_logs = $3::jsonb,
            updated_at = now()
        WHERE id = $4
        """,
        next_status, json.dumps(merged_env), json.dumps(logs), deployment_id,
    )
    return await get_by_id(deployment_id)


async def reset_to_executing(deployment_id: UUID) -> DeploymentSummary:
    """Retry : repasse à executing_step sans changer current_step_index."""
    await execute(
        "UPDATE project_deployments SET status = 'executing_step', updated_at = now() WHERE id = $1",
        deployment_id,
    )
    return await get_by_id(deployment_id)


async def get_ordered_before_scripts(deployment_id: UUID) -> list[Any]:
    """Retourne les group_scripts timing='before' triés par position."""
    from agflow.services import group_scripts_service
    deployment = await get_by_id(deployment_id)
    group_ids = [UUID(gid) for gid in deployment.group_servers.keys()]
    links: list[Any] = []
    for gid in group_ids:
        for link in await group_scripts_service.list_by_group(gid):
            if link.timing == "before":
                links.append(link)
    return sorted(links, key=lambda l: l.position)
```

- [ ] **Step 5 : Vérifier les tests**

```powershell
cd backend; uv run pytest tests/test_deployment_service_wizard.py -v
```

Expected : PASS

- [ ] **Step 6 : Vérifier que les tests existants passent toujours**

```powershell
cd backend; uv run pytest -v
```

Expected : pas de nouvelle régression

- [ ] **Step 7 : Commit**

```bash
git add backend/src/agflow/services/project_deployments_service.py \
        backend/tests/test_deployment_service_wizard.py \
        backend/tests/test_deployment_schemas.py
git commit -m "feat(service): helpers wizard — advance_step, reset_to_executing, get_ordered_before_scripts"
```

---

## Task 4 — ssh_executor : exec streaming

**Files:**
- Modify: `backend/src/agflow/services/ssh_executor.py`

- [ ] **Step 1 : Écrire le test**

Fichier `backend/tests/test_ssh_executor_stream.py` :

```python
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_exec_command_stream_yields_lines():
    """exec_command_stream doit produire des tuples (stream_type, line)."""
    from agflow.services.ssh_executor import exec_command_stream

    lines_received = []

    # Simuler une connexion asyncssh qui retourne deux lignes stdout
    mock_process = MagicMock()
    mock_process.stdin = MagicMock()
    mock_process.stdin.write = MagicMock()
    mock_process.stdin.write_eof = MagicMock()
    mock_process.exit_status = 0

    async def mock_stdout_iter():
        for line in ["line1\n", "line2\n"]:
            yield line

    mock_process.stdout = mock_stdout_iter()

    mock_conn = MagicMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)

    mock_proc_ctx = MagicMock()
    mock_proc_ctx.__aenter__ = AsyncMock(return_value=mock_process)
    mock_proc_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_conn.create_process = MagicMock(return_value=mock_proc_ctx)

    with patch("agflow.services.ssh_executor._connect", new_callable=AsyncMock, return_value=mock_conn):
        async for stream_type, line in exec_command_stream(
            host="h", port=22, username="u", password="p",
            private_key=None, passphrase=None, command="echo test",
        ):
            lines_received.append((stream_type, line))

    assert ("stdout", "line1") in lines_received
    assert ("stdout", "line2") in lines_received
```

- [ ] **Step 2 : Vérifier que le test échoue**

```powershell
cd backend; uv run pytest tests/test_ssh_executor_stream.py -v
```

Expected : FAIL (`exec_command_stream` not found)

- [ ] **Step 3 : Implémenter `exec_command_stream`**

Dans `backend/src/agflow/services/ssh_executor.py`, ajouter après `exec_command` :

```python
from collections.abc import AsyncGenerator


async def exec_command_stream(
    host: str,
    port: int,
    username: str | None,
    password: str | None,
    private_key: str | None,
    passphrase: str | None,
    command: str,
    input: str | None = None,
) -> AsyncGenerator[tuple[str, str], None]:
    """Execute a command via SSH, yielding (stream_type, line) tuples.

    stream_type is 'stdout', 'stderr', or 'exit' (last tuple carries exit code as str).
    """
    conn = await _connect(host, port, username, password, private_key, passphrase)
    async with conn:
        async with conn.create_process(command) as proc:
            if input is not None:
                proc.stdin.write(input)
                proc.stdin.write_eof()
            async for raw_line in proc.stdout:
                yield "stdout", raw_line.rstrip("\n")
            exit_code = proc.exit_status if proc.exit_status is not None else -1
            yield "exit", str(exit_code)
```

- [ ] **Step 4 : Vérifier le test**

```powershell
cd backend; uv run pytest tests/test_ssh_executor_stream.py -v
```

Expected : PASS

- [ ] **Step 5 : Commit**

```bash
git add backend/src/agflow/services/ssh_executor.py \
        backend/tests/test_ssh_executor_stream.py
git commit -m "feat(ssh): exec_command_stream — lecture ligne par ligne avec asyncssh"
```

---

## Task 5 — deployment_log_bus

**Files:**
- Create: `backend/src/agflow/services/deployment_log_bus.py`

- [ ] **Step 1 : Écrire le test**

Fichier `backend/tests/test_deployment_log_bus.py` :

```python
import asyncio
import pytest
from uuid import uuid4
from agflow.services.deployment_log_bus import DeploymentLogBus


@pytest.mark.asyncio
async def test_subscribe_and_publish():
    bus = DeploymentLogBus()
    dep_id = uuid4()
    q = bus.subscribe(dep_id)

    await bus.publish(dep_id, {"type": "log", "line": "hello"})
    event = await asyncio.wait_for(q.get(), timeout=1.0)
    assert event == {"type": "log", "line": "hello"}


@pytest.mark.asyncio
async def test_close_puts_none_sentinel():
    bus = DeploymentLogBus()
    dep_id = uuid4()
    q = bus.subscribe(dep_id)

    await bus.close(dep_id)
    sentinel = await asyncio.wait_for(q.get(), timeout=1.0)
    assert sentinel is None


@pytest.mark.asyncio
async def test_publish_to_unknown_deployment_is_noop():
    bus = DeploymentLogBus()
    dep_id = uuid4()
    # Pas d'abonné — ne doit pas lever d'exception
    await bus.publish(dep_id, {"type": "log", "line": "ignored"})
```

- [ ] **Step 2 : Vérifier que les tests échouent**

```powershell
cd backend; uv run pytest tests/test_deployment_log_bus.py -v
```

Expected : FAIL (module not found)

- [ ] **Step 3 : Implémenter**

Créer `backend/src/agflow/services/deployment_log_bus.py` :

```python
"""Bus in-process de logs de déploiement.

Chaque déploiement actif a une asyncio.Queue. L'executor publie dedans ;
l'endpoint SSE consomme. Scoped au processus — un seul worker uvicorn suffit.
"""
from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import structlog

_log = structlog.get_logger(__name__)


class DeploymentLogBus:
    def __init__(self) -> None:
        self._queues: dict[UUID, list[asyncio.Queue[Any]]] = {}

    def subscribe(self, deployment_id: UUID) -> asyncio.Queue[Any]:
        """Crée et enregistre une queue pour un consommateur SSE."""
        q: asyncio.Queue[Any] = asyncio.Queue()
        self._queues.setdefault(deployment_id, []).append(q)
        return q

    def unsubscribe(self, deployment_id: UUID, q: asyncio.Queue[Any]) -> None:
        listeners = self._queues.get(deployment_id, [])
        if q in listeners:
            listeners.remove(q)
        if not listeners:
            self._queues.pop(deployment_id, None)

    async def publish(self, deployment_id: UUID, event: dict[str, Any]) -> None:
        for q in self._queues.get(deployment_id, []):
            await q.put(event)

    async def close(self, deployment_id: UUID) -> None:
        """Envoie le sentinel None à tous les abonnés puis supprime le canal."""
        for q in self._queues.get(deployment_id, []):
            await q.put(None)
        self._queues.pop(deployment_id, None)


# Singleton applicatif — importé par l'executor et les endpoints SSE.
log_bus = DeploymentLogBus()
```

- [ ] **Step 4 : Vérifier les tests**

```powershell
cd backend; uv run pytest tests/test_deployment_log_bus.py -v
```

Expected : PASS (3/3)

- [ ] **Step 5 : Commit**

```bash
git add backend/src/agflow/services/deployment_log_bus.py \
        backend/tests/test_deployment_log_bus.py
git commit -m "feat(service): deployment_log_bus — bus in-process asyncio.Queue pour les logs SSE"
```

---

## Task 6 — deployment_executor service

**Files:**
- Create: `backend/src/agflow/services/deployment_executor.py`
- Create: `backend/tests/test_deployment_executor.py`

- [ ] **Step 1 : Écrire les tests**

Fichier `backend/tests/test_deployment_executor.py` :

```python
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from uuid import uuid4
from datetime import datetime


def _make_deployment(status="generated", step_index=0, accumulated_env=None):
    from agflow.schemas.products import DeploymentSummary
    return DeploymentSummary(
        id=uuid4(), project_id=uuid4(), user_id=uuid4(),
        status=status, current_step_index=step_index,
        accumulated_env=accumulated_env or {},
        step_logs=[], group_servers={"grp1": "mach1"},
        generated_env="VAR=val", generated_secrets={},
        nullable_secrets=[], generated_data={},
        created_at=datetime.now(), updated_at=datetime.now(),
    )


def _make_link(position=0, timing="before", input_values=None, trigger_rules=None):
    link = MagicMock()
    link.id = uuid4()
    link.script_id = uuid4()
    link.timing = timing
    link.position = position
    link.input_values = input_values or {}
    link.trigger_rules = trigger_rules or []
    link.script_name = "test-script"
    link.machine_name = "test-machine"
    link.env_mapping = {}
    link.group_name = "group1"
    return link


@pytest.mark.asyncio
async def test_execute_step_success_updates_accumulated_env():
    dep = _make_deployment()
    link = _make_link()

    with patch("agflow.services.deployment_executor.project_deployments_service") as mock_svc, \
         patch("agflow.services.deployment_executor.scripts_service") as mock_scripts, \
         patch("agflow.services.deployment_executor._run_script_streaming", new_callable=AsyncMock) as mock_run, \
         patch("agflow.services.deployment_executor.log_bus") as mock_bus:

        mock_svc.get_by_id = AsyncMock(return_value=dep)
        mock_svc.get_ordered_before_scripts = AsyncMock(return_value=[link])
        mock_svc.set_status = AsyncMock()
        mock_svc.advance_step = AsyncMock(return_value=dep)
        mock_svc.reset_to_executing = AsyncMock()

        mock_scripts.get_by_id = AsyncMock(return_value=MagicMock(content="echo '{\"KC_ID\": \"abc\"}'"))

        mock_run.return_value = {
            "success": True, "exit_code": 0,
            "stdout": '{"KC_ID": "abc"}', "stderr": "",
        }
        mock_bus.publish = AsyncMock()
        mock_bus.close = AsyncMock()

        from agflow.services.deployment_executor import execute_step
        await execute_step(dep.id)

        mock_svc.advance_step.assert_awaited_once()
        call_kwargs = mock_svc.advance_step.call_args
        assert call_kwargs.kwargs["next_status"] == "before_complete"
        assert "KC_ID" in call_kwargs.kwargs["new_accumulated_env"]


@pytest.mark.asyncio
async def test_execute_step_failure_sets_step_failed():
    dep = _make_deployment()
    link = _make_link()

    with patch("agflow.services.deployment_executor.project_deployments_service") as mock_svc, \
         patch("agflow.services.deployment_executor.scripts_service") as mock_scripts, \
         patch("agflow.services.deployment_executor._run_script_streaming", new_callable=AsyncMock) as mock_run, \
         patch("agflow.services.deployment_executor.log_bus") as mock_bus:

        mock_svc.get_by_id = AsyncMock(return_value=dep)
        mock_svc.get_ordered_before_scripts = AsyncMock(return_value=[link])
        mock_svc.set_status = AsyncMock()
        mock_scripts.get_by_id = AsyncMock(return_value=MagicMock(content="exit 1"))
        mock_run.return_value = {"success": False, "exit_code": 1, "stdout": "", "stderr": "error"}
        mock_bus.publish = AsyncMock()
        mock_bus.close = AsyncMock()

        from agflow.services.deployment_executor import execute_step
        await execute_step(dep.id)

        mock_svc.set_status.assert_any_await(dep.id, "step_failed")
```

- [ ] **Step 2 : Vérifier que les tests échouent**

```powershell
cd backend; uv run pytest tests/test_deployment_executor.py -v
```

Expected : FAIL (module not found)

- [ ] **Step 3 : Implémenter `deployment_executor.py`**

Créer `backend/src/agflow/services/deployment_executor.py` :

```python
"""Executor de scripts before-deploy step-by-step.

Chaque appel à `execute_step` tourne dans une tâche asyncio.
Il publie ses logs dans le `log_bus` (consommé par le SSE endpoint)
et met à jour la table `project_deployments` (status, accumulated_env, step_logs).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import structlog

from agflow.services import project_deployments_service, scripts_service, ssh_executor
from agflow.services.deployment_log_bus import log_bus

_log = structlog.get_logger(__name__)


async def _run_script_streaming(
    link: Any,
    script_content: str,
    env_text: str,
    on_line: Any,  # callable async (stream_type, line)
) -> dict[str, Any]:
    """Exécute un script SSH en streaming.

    Résout les input_values, substitue les placeholders, upload + exécute.
    Appelle `on_line(stream_type, line)` pour chaque ligne reçue.
    Retourne {success, exit_code, stdout, stderr}.
    """
    import secrets as _secrets

    from agflow.api.admin.project_deployments import (
        _resolve_input_value,
        _ssh_kwargs_for_machine,
        _substitute_script_placeholders,
    )
    from agflow.services import group_scripts_service, platform_secrets_service

    try:
        target_machine_id = await group_scripts_service.resolve_target_machine_id(link.id)
        ssh = await _ssh_kwargs_for_machine(target_machine_id)
    except Exception as exc:
        await on_line("stderr", str(exc))
        return {"success": False, "exit_code": -1, "stdout": "", "stderr": str(exc)}

    platform_secrets_map = await platform_secrets_service.resolve_all()
    resolved_inputs: dict[str, str] = {}
    for name, raw in (link.input_values or {}).items():
        step1 = platform_secrets_service.resolve_platform_refs(raw or "", platform_secrets_map)
        resolved, _ = _resolve_input_value(step1, env_text)
        resolved_inputs[name] = resolved

    rendered = _substitute_script_placeholders(script_content, resolved_inputs)
    remote_path = f"/tmp/agflow-script-{_secrets.token_hex(8)}.sh"

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    exit_code = -1

    try:
        await ssh_executor.exec_command(**ssh, command=f"cat > {remote_path}", input=rendered)
        await ssh_executor.exec_command(**ssh, command=f"chmod +x {remote_path}")

        async for stream_type, line in ssh_executor.exec_command_stream(**ssh, command=f"bash {remote_path}"):
            if stream_type == "exit":
                exit_code = int(line)
            elif stream_type == "stdout":
                stdout_lines.append(line)
                await on_line("stdout", line)
            else:
                stderr_lines.append(line)
                await on_line("stderr", line)
    except Exception as exc:
        await on_line("stderr", str(exc))
        return {"success": False, "exit_code": -1, "stdout": "", "stderr": str(exc)}
    finally:
        try:
            await ssh_executor.exec_command(**ssh, command=f"rm -f {remote_path}")
        except Exception:
            pass

    return {
        "success": exit_code == 0,
        "exit_code": exit_code,
        "stdout": "\n".join(stdout_lines),
        "stderr": "\n".join(stderr_lines),
    }


async def execute_step(deployment_id: UUID) -> None:
    """Tâche asyncio — exécute le step courant et met à jour la DB.

    Appelée par `POST /{id}/execute-step` via `asyncio.create_task`.
    """
    from agflow.api.admin.project_deployments import (
        _collect_env_from_script,
        _evaluate_trigger_rules,
        _merge_env_with_values,
        _parse_env_map,
        _parse_last_json,
    )

    deployment = await project_deployments_service.get_by_id(deployment_id)
    before_scripts = await project_deployments_service.get_ordered_before_scripts(deployment_id)
    step_index = deployment.current_step_index

    if step_index >= len(before_scripts):
        await project_deployments_service.set_status(deployment_id, "before_complete")
        await log_bus.publish(deployment_id, {"type": "before_complete"})
        await log_bus.close(deployment_id)
        return

    link = before_scripts[step_index]

    try:
        script = await scripts_service.get_by_id(link.script_id)
    except scripts_service.ScriptNotFoundError:
        await project_deployments_service.set_status(deployment_id, "step_failed")
        await log_bus.publish(deployment_id, {"type": "step_failed", "step_index": step_index, "exit_code": -1, "error": "script not found"})
        await log_bus.close(deployment_id)
        return

    # Construire le texte d'env courant = generated_env + accumulated_env
    current_env = _merge_env_with_values(
        deployment.generated_env or "",
        {k: str(v) for k, v in deployment.accumulated_env.items()},
    )

    # Évaluer les trigger_rules
    ok, reason = _evaluate_trigger_rules(link.trigger_rules, _parse_env_map(current_env))
    if not ok:
        skipped_log = {
            "step_index": step_index, "lines": [f"[skipped] {reason}"],
            "exit_code": 0, "started_at": datetime.now(timezone.utc).isoformat(),
            "ended_at": datetime.now(timezone.utc).isoformat(),
        }
        await log_bus.publish(deployment_id, {"type": "log", "line": f"[skipped] {reason}", "stream": "info"})
        next_status = "before_complete" if step_index + 1 >= len(before_scripts) else "step_complete"
        await project_deployments_service.advance_step(
            deployment_id,
            new_accumulated_env={},
            new_log=skipped_log,
            next_status=next_status,
        )
        if next_status == "before_complete":
            await log_bus.publish(deployment_id, {"type": "before_complete"})
        else:
            await log_bus.publish(deployment_id, {"type": "step_complete", "step_index": step_index})
        await log_bus.close(deployment_id)
        return

    lines: list[str] = []
    started_at = datetime.now(timezone.utc).isoformat()

    async def on_line(stream_type: str, line: str) -> None:
        lines.append(line)
        await log_bus.publish(deployment_id, {"type": "log", "line": line, "stream": stream_type})

    await log_bus.publish(deployment_id, {"type": "step_start", "step_index": step_index, "script": link.script_name})
    result = await _run_script_streaming(link, script.content, current_env, on_line)
    ended_at = datetime.now(timezone.utc).isoformat()

    step_log = {
        "step_index": step_index, "lines": lines,
        "exit_code": result["exit_code"],
        "started_at": started_at, "ended_at": ended_at,
    }

    if not result["success"]:
        await project_deployments_service.set_status(deployment_id, "step_failed")
        await log_bus.publish(deployment_id, {
            "type": "step_failed", "step_index": step_index,
            "exit_code": result["exit_code"],
        })
        # Stocker le log même en cas d'échec
        deployment2 = await project_deployments_service.get_by_id(deployment_id)
        logs = [s.model_dump() for s in deployment2.step_logs] + [step_log]
        from agflow.db.pool import execute as db_execute
        import json as _json
        await db_execute(
            "UPDATE project_deployments SET step_logs = $1::jsonb, updated_at = now() WHERE id = $2",
            _json.dumps(logs), deployment_id,
        )
        await log_bus.close(deployment_id)
        return

    # Succès : extraire les output vars
    parsed_json = _parse_last_json(result["stdout"])
    new_env_values: dict[str, str] = {}
    if parsed_json:
        env_map = _parse_env_map(current_env)
        new_env_values = _collect_env_from_script(link, parsed_json, env_map)

    next_status = "before_complete" if step_index + 1 >= len(before_scripts) else "step_complete"
    await project_deployments_service.advance_step(
        deployment_id,
        new_accumulated_env=new_env_values,
        new_log=step_log,
        next_status=next_status,
    )

    if next_status == "before_complete":
        await log_bus.publish(deployment_id, {"type": "before_complete"})
    else:
        await log_bus.publish(deployment_id, {"type": "step_complete", "step_index": step_index, "output_vars": new_env_values})

    await log_bus.close(deployment_id)
```

- [ ] **Step 4 : Vérifier les tests**

```powershell
cd backend; uv run pytest tests/test_deployment_executor.py -v
```

Expected : PASS (2/2)

- [ ] **Step 5 : Commit**

```bash
git add backend/src/agflow/services/deployment_executor.py \
        backend/tests/test_deployment_executor.py
git commit -m "feat(service): deployment_executor — execute_step avec streaming SSE et accumulated_env"
```

---

## Task 7 — Nouveaux endpoints backend

**Files:**
- Modify: `backend/src/agflow/api/admin/project_deployments.py`
- Modify: `backend/src/agflow/schemas/products.py` (import GenerateRequest)

- [ ] **Step 1 : Ajouter les imports nécessaires**

En tête de `project_deployments.py`, ajouter/compléter les imports :

```python
import asyncio
import json as _json
from datetime import datetime, timezone

from fastapi.responses import StreamingResponse

from agflow.schemas.products import (
    DeploymentCreate, DeploymentSummary, DeploymentUpdate,
    GenerateRequest, StepLog,
)
from agflow.services.deployment_log_bus import log_bus
from agflow.services import deployment_executor
```

Supprimer la définition locale de `GenerateRequest` dans ce fichier (elle est maintenant dans `schemas/products.py`).

- [ ] **Step 2 : Mettre à jour l'endpoint `generate`**

Remplacer l'endpoint `generate_deployment` existant par :

```python
@router.post("/{deployment_id}/generate", response_model=DeploymentSummary, dependencies=_admin)
async def generate_deployment(deployment_id: UUID, payload: GenerateRequest | None = None):
    try:
        return await project_deployments_service.generate(
            deployment_id,
            user_secrets=payload.user_secrets if payload else None,
            group_vars=payload.group_vars if payload else None,
        )
    except project_deployments_service.DeploymentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
```

Puis dans `project_deployments_service.generate()`, ajouter `group_vars: dict[str, str] | None = None` et, dans la boucle de variables de groupe, donner la priorité à `group_vars` quand la clé est présente :

```python
# Dans la boucle group_variables_service.list_by_group :
for var in await group_variables_service.list_by_group(g.id):
    if group_vars and var.name in group_vars:
        env_vars[var.name] = group_vars[var.name]
    else:
        resolved = platform_secrets_service.resolve_platform_refs(
            var.value, platform_secrets_map,
        )
        env_vars[var.name] = resolved
```

- [ ] **Step 3 : Ajouter `execute-step`**

```python
@router.post("/{deployment_id}/execute-step", dependencies=_admin, status_code=202)
async def execute_step_endpoint(deployment_id: UUID) -> dict[str, str]:
    """Lance l'exécution du step courant en tâche asyncio. Retourne 202 immédiatement."""
    try:
        deployment = await project_deployments_service.get_by_id(deployment_id)
    except project_deployments_service.DeploymentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    allowed = {"generated", "step_complete"}
    if deployment.status not in allowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot execute step from status '{deployment.status}'. Expected: {allowed}",
        )

    await project_deployments_service.set_status(deployment_id, "executing_step")
    asyncio.create_task(deployment_executor.execute_step(deployment_id))
    return {"status": "accepted"}
```

- [ ] **Step 4 : Ajouter `retry-step`**

```python
@router.post("/{deployment_id}/retry-step", dependencies=_admin, status_code=202)
async def retry_step_endpoint(deployment_id: UUID) -> dict[str, str]:
    """Réessaie le step courant (status doit être step_failed)."""
    try:
        deployment = await project_deployments_service.get_by_id(deployment_id)
    except project_deployments_service.DeploymentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    if deployment.status != "step_failed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot retry from status '{deployment.status}'. Expected: step_failed",
        )

    await project_deployments_service.reset_to_executing(deployment_id)
    asyncio.create_task(deployment_executor.execute_step(deployment_id))
    return {"status": "accepted"}
```

- [ ] **Step 5 : Ajouter le SSE stream endpoint**

```python
@router.get("/{deployment_id}/stream", dependencies=_admin)
async def stream_deployment_logs(deployment_id: UUID) -> StreamingResponse:
    """SSE : stream des logs du step en cours.

    Format des events :
      data: {"type": "log", "line": "...", "stream": "stdout"}
      data: {"type": "step_complete", "step_index": 0, "output_vars": {...}}
      data: {"type": "step_failed", "step_index": 0, "exit_code": 1}
      data: {"type": "before_complete"}
    """
    try:
        await project_deployments_service.get_by_id(deployment_id)
    except project_deployments_service.DeploymentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    q = log_bus.subscribe(deployment_id)

    async def event_generator():
        try:
            while True:
                event = await asyncio.wait_for(q.get(), timeout=30.0)
                if event is None:  # sentinel = fin du stream
                    break
                yield f"data: {_json.dumps(event)}\n\n"
        except asyncio.TimeoutError:
            yield "data: {\"type\": \"keepalive\"}\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            log_bus.unsubscribe(deployment_id, q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
```

- [ ] **Step 6 : Ajouter l'endpoint `deploy` (refactorisé depuis push)**

```python
@router.post("/{deployment_id}/deploy")
async def deploy_endpoint(deployment_id: UUID, user_id: UUID = Depends(_get_user_id)):
    """Déploiement final SSH (docker-compose / stack) après before_complete.

    Reprend la logique de push mais part de accumulated_env déjà construit.
    """
    try:
        deployment = await project_deployments_service.get_by_id(deployment_id)
    except project_deployments_service.DeploymentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    if deployment.status != "before_complete":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot deploy from status '{deployment.status}'. Expected: before_complete",
        )

    await project_deployments_service.set_status(deployment_id, "deploying")

    # Construire l'env final = generated_env + accumulated_env
    accumulated = {k: str(v) for k, v in deployment.accumulated_env.items()}
    env_text = _merge_env_with_values(deployment.generated_env or "", accumulated)

    project = await projects_service.get_by_id(deployment.project_id)
    project_slug = project.display_name.lower().replace(" ", "-")

    results: list[dict[str, Any]] = []

    # Créer project_runtime + group_runtimes (même logique que push)
    collected_env: dict[str, str] = {**accumulated}
    project_runtime_id, project_runtime_seq = await project_runtimes_service.upsert_project_runtime(
        project_id=deployment.project_id,
        deployment_id=deployment.id,
        user_id=user_id,
    )
    collected_env["PROJECT_RUNTIME_SEQ"] = str(project_runtime_seq)

    project_groups = await groups_service.list_by_project(deployment.project_id)
    groups_by_id = {str(g.id): g for g in project_groups}
    for gid_str, mid_str in deployment.group_servers.items():
        try:
            gid = UUID(gid_str)
            mid = UUID(mid_str) if mid_str else None
        except Exception:
            continue
        runtime_id = await project_runtimes_service.upsert_group_runtime(
            project_runtime_id=project_runtime_id, group_id=gid, machine_id=mid,
        )
        group = groups_by_id.get(gid_str)
        if group:
            slug = re.sub(r"[^A-Z0-9]", "_", (group.name or "").upper())
            collected_env[f"{slug}_RUNTIME_ID"] = str(runtime_id)

    env_text = _merge_env_with_values(env_text, collected_env)

    # Déploiement SSH (même logique que push à partir de machine_ids)
    machine_ids = set(deployment.group_servers.values())
    for machine_id_str in machine_ids:
        machine_id = UUID(machine_id_str)
        try:
            machine = await infra_machines_service.get_by_id(machine_id)
            creds = await infra_machines_service.get_credentials(machine_id)
        except Exception as exc:
            results.append({"server": machine_id_str, "success": False, "error": str(exc)})
            continue

        private_key = None
        passphrase = None
        if creds.get("certificate_id"):
            cert = await infra_certificates_service.get_decrypted(creds["certificate_id"])
            private_key = cert.get("private_key")
            passphrase = cert.get("passphrase")

        remote_dir = f"~/agflow.docker/projects/{project_slug}-{project_runtime_seq}"
        group_ids_on_machine = [
            UUID(gid) for gid, mid in deployment.group_servers.items()
            if mid == str(machine_id)
        ]
        compose_fragments: list[str] = []
        render_failed: str | None = None
        for gid in group_ids_on_machine:
            try:
                fragment = await compose_renderer_service.render_group_compose(deployment.generated_data, gid)
            except compose_renderer_service.ComposeRenderError as exc:
                render_failed = str(exc)
                break
            compose_fragments.append(fragment)
        if render_failed:
            results.append({"server": machine.name or machine.host, "success": False, "error": render_failed})
            continue
        compose_content = "\n".join(compose_fragments)

        try:
            login_steps = await _build_registry_login_steps(compose_content, _parse_env_map(env_text))
        except RegistryCredentialError as exc:
            results.append({"server": machine.name or machine.host, "success": False, "error": str(exc)})
            continue

        stack_name = f"agflow-proj-{project_slug}-{project_runtime_seq}"
        steps = swarm_deploy_steps.build_deploy_steps(
            remote_dir=remote_dir, compose_content=compose_content,
            env_content=env_text, stack_name=stack_name,
            extra_steps_before_deploy=login_steps,
        )
        ssh_kwargs = {
            "host": creds["host"], "port": creds["port"],
            "username": creds["username"], "password": creds["password"],
            "private_key": private_key, "passphrase": passphrase,
        }

        failed_step: str | None = None
        try:
            for step_name, cmd, stdin in steps:
                r = await ssh_executor.exec_command(**ssh_kwargs, command=cmd, input=stdin)
                if r.get("exit_code") != 0:
                    failed_step = step_name
                    break
        except Exception as exc:
            results.append({"server": machine.name or machine.host, "success": False, "error": str(exc)})
            continue

        results.append({
            "server": machine.name or machine.host,
            "machine_id": str(machine_id),
            "success": failed_step is None,
            "step": failed_step,
        })

    all_ok = all(r.get("success") for r in results)
    final_status = "deployed" if all_ok else "failed"
    await project_deployments_service.set_status(deployment_id, final_status)

    # After-scripts (même que push, non-bloquant sur les erreurs)
    after_links: list[Any] = []
    group_ids_in_deploy = [UUID(gid) for gid in deployment.group_servers.keys()]
    for gid in group_ids_in_deploy:
        for link in await group_scripts_service.list_by_group(gid):
            if link.timing == "after":
                after_links.append(link)
    after_links.sort(key=lambda l: l.position)
    for link in after_links:
        try:
            script = await scripts_service.get_by_id(link.script_id)
            await _run_group_script(link, script.content, env_text=env_text)
        except Exception:
            pass

    return {"results": results, "status": final_status}
```

- [ ] **Step 7 : Vérifier la syntaxe et le lint**

```powershell
cd backend
uv run ruff check src/agflow/api/admin/project_deployments.py
uv run ruff check src/agflow/services/project_deployments_service.py
```

Expected : pas d'erreur (corriger si nécessaire)

- [ ] **Step 8 : Lancer les tests existants**

```powershell
cd backend; uv run pytest -v
```

Expected : pas de régression sur les tests existants

- [ ] **Step 9 : Commit**

```bash
git add backend/src/agflow/api/admin/project_deployments.py \
        backend/src/agflow/services/project_deployments_service.py
git commit -m "feat(api): execute-step, retry-step, stream SSE, deploy — wizard step-by-step"
```

---

## Task 8 — Frontend : API client

**Files:**
- Modify: `frontend/src/lib/projectsApi.ts`

- [ ] **Step 1 : Mettre à jour `DeploymentSummary` et ajouter les méthodes**

Dans `frontend/src/lib/projectsApi.ts`, mettre à jour l'interface `DeploymentSummary` :

```typescript
export interface StepLog {
  step_index: number;
  lines: string[];
  exit_code: number;
  started_at?: string;
  ended_at?: string;
}

export type DeploymentStatus =
  | "draft" | "generated"
  | "executing_step" | "step_complete" | "step_failed" | "before_complete"
  | "deploying" | "deployed" | "failed";

export interface DeploymentSummary {
  id: string;
  project_id: string;
  user_id: string;
  group_servers: Record<string, string>;
  status: DeploymentStatus;
  current_step_index: number;
  accumulated_env: Record<string, string>;
  step_logs: StepLog[];
  generated_compose?: string;
  generated_env?: string;
  generated_secrets: Record<string, string>;
  nullable_secrets: string[];
  generated_data: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}
```

Ajouter les méthodes dans `deploymentsApi` :

```typescript
async generate(
  id: string,
  userSecrets?: Record<string, string>,
  groupVars?: Record<string, string>,
): Promise<DeploymentSummary> {
  const { data } = await apiClient.post<DeploymentSummary>(
    `/api/admin/project-deployments/${id}/generate`,
    { user_secrets: userSecrets ?? {}, group_vars: groupVars ?? {} },
  );
  return data;
},

async executeStep(id: string): Promise<void> {
  await apiClient.post(`/api/admin/project-deployments/${id}/execute-step`);
},

async retryStep(id: string): Promise<void> {
  await apiClient.post(`/api/admin/project-deployments/${id}/retry-step`);
},

async deploy(id: string): Promise<{ results: unknown[]; status: string }> {
  const { data } = await apiClient.post(
    `/api/admin/project-deployments/${id}/deploy`,
  );
  return data;
},

streamLogs(id: string): EventSource {
  return new EventSource(`/api/admin/project-deployments/${id}/stream`);
},
```

- [ ] **Step 2 : Vérifier TypeScript**

```powershell
cd frontend; npx tsc --noEmit
```

Expected : pas d'erreur

- [ ] **Step 3 : Commit**

```bash
git add frontend/src/lib/projectsApi.ts
git commit -m "feat(api-client): DeploymentSummary wizard fields + executeStep/retryStep/deploy/streamLogs"
```

---

## Task 9 — Frontend : i18n

**Files:**
- Modify: `frontend/src/i18n/fr.json`
- Modify: `frontend/src/i18n/en.json`

- [ ] **Step 1 : Ajouter les clés dans `fr.json`**

Dans la section `"deploy"` (ou en créer une) :

```json
"deploy_wizard_tab_config": "Configuration",
"deploy_wizard_tab_exec": "Exécution",
"deploy_wizard_tab_logs": "Logs",
"deploy_wizard_next": "Suivant",
"deploy_wizard_execute": "Exécuter",
"deploy_wizard_retry": "Réessayer",
"deploy_wizard_deploy": "Déployer",
"deploy_wizard_step_count": "Étape {{current}}/{{total}}",
"deploy_wizard_step_waiting": "En attente",
"deploy_wizard_step_running": "En cours…",
"deploy_wizard_step_done": "Terminé",
"deploy_wizard_step_failed": "Échoué",
"deploy_wizard_step_skipped": "Ignoré",
"deploy_wizard_vars_required": "Variables requises",
"deploy_wizard_var_missing": "manquant",
"deploy_wizard_no_steps": "Aucun script before configuré pour ce déploiement.",
"deploy_wizard_live": "En direct",
"deploy_wizard_archived": "Archivé",
"deploy_wizard_step_select": "Étape {{index}}",
"deploy_wizard_deploying": "Déploiement en cours…",
"deploy_wizard_deployed_ok": "Déploiement réussi",
"deploy_wizard_deployed_fail": "Déploiement échoué",
"deploy_wizard_group_vars_title": "Variables du groupe"
```

- [ ] **Step 2 : Ajouter les clés dans `en.json`**

```json
"deploy_wizard_tab_config": "Configuration",
"deploy_wizard_tab_exec": "Execution",
"deploy_wizard_tab_logs": "Logs",
"deploy_wizard_next": "Next",
"deploy_wizard_execute": "Execute",
"deploy_wizard_retry": "Retry",
"deploy_wizard_deploy": "Deploy",
"deploy_wizard_step_count": "Step {{current}}/{{total}}",
"deploy_wizard_step_waiting": "Waiting",
"deploy_wizard_step_running": "Running…",
"deploy_wizard_step_done": "Done",
"deploy_wizard_step_failed": "Failed",
"deploy_wizard_step_skipped": "Skipped",
"deploy_wizard_vars_required": "Required variables",
"deploy_wizard_var_missing": "missing",
"deploy_wizard_no_steps": "No before-scripts configured for this deployment.",
"deploy_wizard_live": "Live",
"deploy_wizard_archived": "Archived",
"deploy_wizard_step_select": "Step {{index}}",
"deploy_wizard_deploying": "Deploying…",
"deploy_wizard_deployed_ok": "Deployment succeeded",
"deploy_wizard_deployed_fail": "Deployment failed",
"deploy_wizard_group_vars_title": "Group variables"
```

- [ ] **Step 3 : Vérifier TypeScript**

```powershell
cd frontend; npx tsc --noEmit
```

- [ ] **Step 4 : Commit**

```bash
git add frontend/src/i18n/fr.json frontend/src/i18n/en.json
git commit -m "feat(i18n): clés wizard déploiement step-by-step"
```

---

## Task 10 — DeployWizardDialog component

**Files:**
- Create: `frontend/src/components/projects/DeployWizardDialog.tsx`

Le composant reçoit en props le déploiement courant et les variables de groupe par groupe.

- [ ] **Step 1 : Créer la structure du composant**

```typescript
// frontend/src/components/projects/DeployWizardDialog.tsx
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Loader2, CheckCircle2, XCircle, Clock, SkipForward } from "lucide-react";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { deploymentsApi, DeploymentSummary, StepLog } from "@/lib/projectsApi";

// ─── Types ────────────────────────────────────────────────────────────────────

interface GroupVar {
  name: string;
  value: string;
}

interface StepInfo {
  script_name: string;
  machine_name: string;
  input_variables: Array<{ name: string; resolved: boolean }>;
  position: number;
}

interface Props {
  open: boolean;
  onClose: () => void;
  deployment: DeploymentSummary;
  groupVars: GroupVar[];         // variables du groupe, pré-remplies depuis la DB
  steps: StepInfo[];             // scripts before, ordonnés par position
  projectId: string;
}

// ─── Icône de statut step ────────────────────────────────────────────────────

function StepStatusIcon({ status }: { status: string }) {
  if (status === "done") return <CheckCircle2 className="w-4 h-4 text-green-500" />;
  if (status === "failed") return <XCircle className="w-4 h-4 text-red-500" />;
  if (status === "running") return <Loader2 className="w-4 h-4 animate-spin text-blue-500" />;
  if (status === "skipped") return <SkipForward className="w-4 h-4 text-muted-foreground" />;
  return <Clock className="w-4 h-4 text-muted-foreground" />;
}

// ─── Composant principal ──────────────────────────────────────────────────────

export function DeployWizardDialog({ open, onClose, deployment, groupVars, steps, projectId }: Props) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [activeTab, setActiveTab] = useState("config");
  const [localVars, setLocalVars] = useState<Record<string, string>>(() =>
    Object.fromEntries(groupVars.map((v) => [v.name, v.value]))
  );
  const [dep, setDep] = useState<DeploymentSummary>(deployment);
  const [logs, setLogs] = useState<string[]>([]);
  const [selectedStepLog, setSelectedStepLog] = useState<number | null>(null);
  const [isLive, setIsLive] = useState(false);
  const logsEndRef = useRef<HTMLDivElement>(null);
  const esRef = useRef<EventSource | null>(null);

  // Synchroniser le déploiement externe
  useEffect(() => { setDep(deployment); }, [deployment]);

  // Auto-scroll logs
  useEffect(() => {
    if (isLive) logsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs, isLive]);

  // Cleanup SSE à la fermeture
  useEffect(() => {
    if (!open) {
      esRef.current?.close();
      esRef.current = null;
      setIsLive(false);
    }
  }, [open]);

  const openSSE = (depId: string) => {
    esRef.current?.close();
    const es = deploymentsApi.streamLogs(depId);
    esRef.current = es;
    setIsLive(true);
    setLogs([]);
    setActiveTab("logs");

    es.onmessage = (ev) => {
      try {
        const event = JSON.parse(ev.data) as Record<string, unknown>;
        if (event.type === "log") {
          setLogs((prev) => [...prev, String(event.line ?? "")]);
        } else if (event.type === "step_complete" || event.type === "before_complete" || event.type === "step_failed") {
          setIsLive(false);
          es.close();
          // Recharger le déploiement
          qc.invalidateQueries({ queryKey: ["deployments", projectId] });
          setActiveTab("exec");
        } else if (event.type === "step_start") {
          setLogs((prev) => [...prev, `▶ ${String(event.script ?? "")}`]);
        }
      } catch {
        // ignore parse errors
      }
    };
    es.onerror = () => {
      setIsLive(false);
      es.close();
    };
  };

  const handleGenerate = async () => {
    try {
      const updated = await deploymentsApi.generate(dep.id, {}, localVars);
      setDep(updated);
      qc.invalidateQueries({ queryKey: ["deployments", projectId] });
      setActiveTab("exec");
      toast.success(t("deploy_generated"));
    } catch {
      toast.error(t("deploy_generate_error") ?? "Erreur lors de la génération");
    }
  };

  const handleExecuteStep = async () => {
    openSSE(dep.id);
    try {
      await deploymentsApi.executeStep(dep.id);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Erreur";
      toast.error(msg);
      setIsLive(false);
    }
  };

  const handleRetry = async () => {
    openSSE(dep.id);
    try {
      await deploymentsApi.retryStep(dep.id);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Erreur";
      toast.error(msg);
      setIsLive(false);
    }
  };

  const handleDeploy = async () => {
    try {
      setDep((d) => ({ ...d, status: "deploying" }));
      const result = await deploymentsApi.deploy(dep.id);
      qc.invalidateQueries({ queryKey: ["deployments", projectId] });
      if (result.status === "deployed") {
        toast.success(t("deploy_wizard_deployed_ok"));
      } else {
        toast.error(t("deploy_wizard_deployed_fail"));
      }
      setDep((d) => ({ ...d, status: result.status as DeploymentSummary["status"] }));
    } catch {
      toast.error(t("deploy_wizard_deployed_fail"));
    }
  };

  // ─── Render helpers ───────────────────────────────────────────────────────

  const currentIdx = dep.current_step_index;
  const stepStatus = (idx: number): string => {
    if (idx < currentIdx) return "done";
    if (idx === currentIdx) {
      if (dep.status === "executing_step") return "running";
      if (dep.status === "step_failed") return "failed";
      if (dep.status === "step_complete" || dep.status === "before_complete") return "done";
    }
    return "waiting";
  };

  const canExecute =
    (dep.status === "generated" || dep.status === "step_complete") &&
    currentIdx < steps.length;

  const canRetry = dep.status === "step_failed";
  const canDeploy = dep.status === "before_complete";

  const displayedLogs =
    selectedStepLog !== null
      ? (dep.step_logs.find((s) => s.step_index === selectedStepLog)?.lines ?? [])
      : logs;

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) onClose(); }}>
      <DialogContent className="sm:max-w-[960px] h-[820px] flex flex-col">
        <DialogHeader>
          <DialogTitle>{t("deploy_title")}</DialogTitle>
        </DialogHeader>

        <Tabs value={activeTab} onValueChange={setActiveTab} className="flex flex-col flex-1 min-h-0">
          <TabsList className="shrink-0">
            <TabsTrigger value="config">{t("deploy_wizard_tab_config")}</TabsTrigger>
            <TabsTrigger value="exec">{t("deploy_wizard_tab_exec")}</TabsTrigger>
            <TabsTrigger value="logs">{t("deploy_wizard_tab_logs")}</TabsTrigger>
          </TabsList>

          {/* ── Onglet Configuration ── */}
          <TabsContent value="config" className="flex flex-col flex-1 min-h-0 overflow-auto gap-4 p-1">
            {groupVars.length > 0 && (
              <div className="space-y-2">
                <p className="text-sm font-medium">{t("deploy_wizard_group_vars_title")}</p>
                <div className="grid grid-cols-[1fr_2fr] gap-2 items-center">
                  {groupVars.map((v) => (
                    <>
                      <Label key={`lbl-${v.name}`} className="text-xs font-mono">{v.name}</Label>
                      <Input
                        key={`inp-${v.name}`}
                        value={localVars[v.name] ?? ""}
                        onChange={(e) => setLocalVars((prev) => ({ ...prev, [v.name]: e.target.value }))}
                        className="h-7 text-xs font-mono"
                      />
                    </>
                  ))}
                </div>
              </div>
            )}
            <div className="mt-auto flex justify-end">
              <Button onClick={handleGenerate} disabled={dep.status !== "draft"}>
                {t("deploy_wizard_next")}
              </Button>
            </div>
          </TabsContent>

          {/* ── Onglet Exécution ── */}
          <TabsContent value="exec" className="flex flex-col flex-1 min-h-0 overflow-auto gap-3 p-1">
            {steps.length === 0 && (
              <p className="text-sm text-muted-foreground">{t("deploy_wizard_no_steps")}</p>
            )}
            <div className="space-y-2">
              {steps.map((step, idx) => (
                <div
                  key={idx}
                  className={`flex items-center gap-3 rounded-md border px-3 py-2 text-sm ${idx === currentIdx ? "border-primary/40 bg-primary/5" : "border-border"}`}
                >
                  <StepStatusIcon status={stepStatus(idx)} />
                  <span className="flex-1 font-medium">{step.script_name}</span>
                  <span className="text-xs text-muted-foreground">{step.machine_name}</span>
                  <span className="text-xs text-muted-foreground">
                    {t("deploy_wizard_step_count", { current: idx + 1, total: steps.length })}
                  </span>
                </div>
              ))}
            </div>

            <div className="mt-auto flex justify-end gap-2">
              {canRetry && (
                <Button variant="outline" onClick={handleRetry}>
                  {t("deploy_wizard_retry")}
                </Button>
              )}
              {canExecute && (
                <Button onClick={handleExecuteStep}>
                  {t("deploy_wizard_execute")}
                </Button>
              )}
              {canDeploy && (
                <Button onClick={handleDeploy}>
                  {t("deploy_wizard_deploy")}
                </Button>
              )}
            </div>
          </TabsContent>

          {/* ── Onglet Logs ── */}
          <TabsContent value="logs" className="flex flex-col flex-1 min-h-0 p-1 gap-2">
            <div className="flex items-center gap-2 shrink-0">
              {dep.step_logs.map((sl) => (
                <Button
                  key={sl.step_index}
                  variant={selectedStepLog === sl.step_index ? "default" : "outline"}
                  size="sm"
                  className="h-6 text-xs"
                  onClick={() => setSelectedStepLog(sl.step_index)}
                >
                  {t("deploy_wizard_step_select", { index: sl.step_index + 1 })}
                </Button>
              ))}
              {isLive && (
                <Button
                  variant={selectedStepLog === null ? "default" : "outline"}
                  size="sm"
                  className="h-6 text-xs"
                  onClick={() => setSelectedStepLog(null)}
                >
                  <span className="relative flex h-2 w-2 mr-1">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
                    <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500" />
                  </span>
                  {t("deploy_wizard_live")}
                </Button>
              )}
            </div>
            <div className="flex-1 min-h-0 overflow-auto rounded-md bg-zinc-950 p-3 font-mono text-xs text-zinc-200">
              {displayedLogs.map((line, i) => (
                <div key={i}>{line || " "}</div>
              ))}
              {isLive && selectedStepLog === null && <div ref={logsEndRef} />}
            </div>
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 2 : Vérifier TypeScript**

```powershell
cd frontend; npx tsc --noEmit
```

Expected : pas d'erreur (corriger les types si nécessaire)

- [ ] **Step 3 : Commit**

```bash
git add frontend/src/components/projects/DeployWizardDialog.tsx
git commit -m "feat(ui): DeployWizardDialog — wizard 3-onglets (Config/Exec/Logs) avec SSE"
```

---

## Task 11 — Intégration dans ProjectDetailPage

**Files:**
- Modify: `frontend/src/pages/ProjectDetailPage.tsx`

- [ ] **Step 1 : Lire les lignes du DeployDialog existant**

Lire `frontend/src/pages/ProjectDetailPage.tsx` lignes 413–669 pour identifier :
- La définition du composant `DeployDialog`
- Les props reçues (deployment, groupVars, etc.)
- L'endroit dans le JSX où il est rendu

- [ ] **Step 2 : Identifier les données à passer au wizard**

Dans la page, les données existantes à passer au `DeployWizardDialog` :
- `deployment` : objet `DeploymentSummary` (déjà disponible)
- `groupVars` : liste des variables de groupe — extraire depuis les groupes du projet (déjà chargés dans la page via la query existante)
- `steps` : liste des group_scripts timing='before' du déploiement — il faut les charger. Ajouter une query :

```typescript
const { data: beforeScripts = [] } = useQuery({
  queryKey: ["deployment-before-scripts", selectedDeployment?.id],
  queryFn: () => deploymentsApi.get(selectedDeployment!.id).then((d) =>
    // Les scripts sont dans generated_data si présents, sinon vider
    // NOTE: le backend doit exposer les scripts — voir ci-dessous
    []
  ),
  enabled: !!selectedDeployment?.id && selectedDeployment.status !== "draft",
});
```

**Note :** Les `steps` (group_scripts avec leur machine_name et input_variables) ne sont pas encore exposés dans l'API publique. Pour le MVP wizard, on peut construire les `StepInfo` à partir de `generated_data` qui contient les informations des groupes. Alternativement, exposer un endpoint `GET /{id}/steps` qui retourne les scripts before ordonnés.

**Approche pragmatique pour le MVP :** Ajouter un endpoint `GET /{deployment_id}/before-steps` dans le backend qui retourne les scripts before avec leur statut :

```python
@router.get("/{deployment_id}/before-steps", dependencies=_admin)
async def get_before_steps(deployment_id: UUID) -> list[dict[str, Any]]:
    """Retourne les group_scripts before ordonnés, avec machine et input vars."""
    deployment = await project_deployments_service.get_by_id(deployment_id)
    links = await project_deployments_service.get_ordered_before_scripts(deployment_id)
    result = []
    for link in links:
        result.append({
            "script_name": link.script_name,
            "machine_name": link.machine_name,
            "position": link.position,
            "timing": link.timing,
            "input_variables": [
                {"name": k, "resolved": bool(v)}
                for k, v in (link.input_values or {}).items()
            ],
        })
    return result
```

Et côté frontend dans `projectsApi.ts` :

```typescript
async getBeforeSteps(id: string): Promise<StepInfo[]> {
  const { data } = await apiClient.get<StepInfo[]>(
    `/api/admin/project-deployments/${id}/before-steps`,
  );
  return data;
},
```

Ajouter l'interface :

```typescript
export interface StepInfo {
  script_name: string;
  machine_name: string;
  position: number;
  timing: string;
  input_variables: Array<{ name: string; resolved: boolean }>;
}
```

- [ ] **Step 3 : Ajouter la query `beforeSteps` dans la page**

Dans `ProjectDetailPage.tsx`, à l'endroit où les queries de déploiement sont définies, ajouter :

```typescript
const { data: beforeSteps = [] } = useQuery({
  queryKey: ["deployment-before-steps", selectedDeployment?.id],
  queryFn: () => deploymentsApi.getBeforeSteps(selectedDeployment!.id),
  enabled: !!selectedDeployment?.id && selectedDeployment.status !== "draft",
  staleTime: 30_000,
});
```

- [ ] **Step 4 : Construire `groupVarsForWizard`**

Les variables de groupe sont déjà chargées dans la page (via `GroupVariablesSection`). Construire la liste pour le wizard :

```typescript
// Dans le composant, là où groupVars sont disponibles :
const groupVarsForWizard = useMemo(() =>
  allGroupVars.map((v) => ({ name: v.name, value: v.value ?? "" })),
  [allGroupVars]
);
```

- [ ] **Step 5 : Remplacer `<DeployDialog` par `<DeployWizardDialog`**

Importer :

```typescript
import { DeployWizardDialog } from "@/components/projects/DeployWizardDialog";
```

Remplacer l'usage dans le JSX (chercher `<DeployDialog`) par :

```tsx
<DeployWizardDialog
  open={deployDialogOpen}
  onClose={() => setDeployDialogOpen(false)}
  deployment={selectedDeployment}
  groupVars={groupVarsForWizard}
  steps={beforeSteps}
  projectId={project.id}
/>
```

- [ ] **Step 6 : Vérifier TypeScript**

```powershell
cd frontend; npx tsc --noEmit
```

Expected : pas d'erreur

- [ ] **Step 7 : Lancer le serveur dev et tester manuellement**

```powershell
# Terminal 1 — backend
cd backend; uv run uvicorn agflow.main:app --reload

# Terminal 2 — frontend
cd frontend; npm run dev
```

Test manuel (golden path) :
1. Ouvrir un projet avec au moins un déploiement en status `draft`
2. Cliquer sur "Déployer" → dialog s'ouvre sur l'onglet Configuration
3. Modifier une variable de groupe
4. Cliquer "Suivant" → status passe à `generated`, onglet Exécution apparaît
5. Cliquer "Exécuter" → onglet Logs s'ouvre, logs apparaissent en temps réel
6. À la fin du step → retour onglet Exécution, step coché vert
7. Cliquer "Déployer" (si before_complete) → déploiement final

- [ ] **Step 8 : Vérifier l'absence d'erreurs console**

Ouvrir les DevTools, vérifier : pas d'erreur JavaScript, pas de 4xx/5xx inattendus.

- [ ] **Step 9 : Commit**

```bash
git add frontend/src/pages/ProjectDetailPage.tsx \
        frontend/src/lib/projectsApi.ts \
        backend/src/agflow/api/admin/project_deployments.py
git commit -m "feat(ui): intégration DeployWizardDialog dans ProjectDetailPage + endpoint before-steps"
```

---

## Récapitulatif des commits attendus

1. `feat(db): migration 002 — deploy wizard columns + statuts étendus`
2. `feat(schemas): DeploymentStatus étendu, StepLog, GenerateRequest.group_vars`
3. `feat(service): helpers wizard — advance_step, reset_to_executing, get_ordered_before_scripts`
4. `feat(ssh): exec_command_stream — lecture ligne par ligne avec asyncssh`
5. `feat(service): deployment_log_bus — bus in-process asyncio.Queue pour les logs SSE`
6. `feat(service): deployment_executor — execute_step avec streaming SSE et accumulated_env`
7. `feat(api): execute-step, retry-step, stream SSE, deploy — wizard step-by-step`
8. `feat(api-client): DeploymentSummary wizard fields + executeStep/retryStep/deploy/streamLogs`
9. `feat(i18n): clés wizard déploiement step-by-step`
10. `feat(ui): DeployWizardDialog — wizard 3-onglets (Config/Exec/Logs) avec SSE`
11. `feat(ui): intégration DeployWizardDialog dans ProjectDetailPage + endpoint before-steps`
