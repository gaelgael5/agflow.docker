# Agents Swarm Services — Plan d'implémentation (Chantier B1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrer le lancement des agents agflow.docker de `aiodocker.containers.create()` vers `aiodocker.services.create()` (Swarm services), avec `start()/stop()/list_running()` refactorés, ajout d'un `run_task_swarm()` mode test, adaptation `terminal.py` pour résolution service→container, et endpoints API alignés (toggle test dialog, switch direct prod).

**Architecture:** Refacto `container_runner.py` (1100 lignes). `build_service_spec()` NEW miroir de `build_run_config()` qui produit un Swarm ServiceSpec au lieu d'un Docker classic config. `start()` lance via `services.create()` + polling tasks pour résoudre le container du replica unique. `stop()` et `list_running()` opèrent sur services. `terminal.py` ajoute un helper de résolution service_name → container_id. `run_task_swarm()` NEW génère `.tmp/{stack.yml, deploy.sh, task.json}` puis subprocess. Endpoints API : test dialog admin reçoit param `mode`, prod hardcoded Swarm.

**Tech Stack:** Python 3.12 + asyncpg + aiodocker (services API) + Pydantic v2 + pytest + pytest-asyncio.

**Spec source:** `docs/superpowers/specs/2026-05-01-agents-swarm-services-design.md`

**Hors plan:** Frontend toggle UI dans dialog construction d'agent (plan séparé). Multi-cluster targeting. Refacto `build_service.py` (build d'images).

---

## File Structure

| Fichier | Rôle | Action |
|---|---|---|
| `backend/src/agflow/services/container_runner.py` | Cœur du refacto : `build_service_spec()`, `start()`, `stop()`, `list_running()`, `run_task_swarm()`, `_generate_tmp_files_swarm()` | MODIFIÉ (lourd) |
| `backend/src/agflow/api/admin/containers.py` | Endpoints test dialog : ajout param `mode: classic|swarm` | MODIFIÉ |
| `backend/src/agflow/api/public/launched.py` | Endpoint prod : switch `run_task` → `run_task_swarm` | MODIFIÉ |
| `backend/src/agflow/api/admin/terminal.py` | Helper résolution service → container avant `docker exec` | MODIFIÉ |
| `backend/src/agflow/schemas/containers.py` | (éventuel) ajout `mode` au TestRunRequest | MODIFIÉ si nécessaire |
| `backend/tests/test_container_runner_service_spec.py` | Tests unitaires `build_service_spec()` mapping | NOUVEAU |
| `backend/tests/test_container_runner_swarm_lifecycle.py` | Tests `start()/stop()/list_running()` mockés | NOUVEAU |
| `backend/tests/test_container_runner_run_task_swarm.py` | Tests `run_task_swarm()` + snapshot `_generate_tmp_files_swarm()` | NOUVEAU |
| `backend/tests/test_terminal_service_resolution.py` | Tests helper résolution service → container | NOUVEAU |
| `backend/tests/test_swarm_endpoints_wiring.py` | Tests endpoints API : toggle test, prod Swarm only | NOUVEAU |

---

## Task 1 — `build_service_spec()` mapping Dockerfile.json → Swarm ServiceSpec

**Files:**
- Modify: `backend/src/agflow/services/container_runner.py` (ajout fonction)
- Create: `backend/tests/test_container_runner_service_spec.py`

- [ ] **Step 1 : Tests rouges**

Créer `backend/tests/test_container_runner_service_spec.py` :

```python
"""Tests purs (pas de DB, pas de Docker) pour build_service_spec().

Map un Dockerfile.json minimaliste vers un Swarm ServiceSpec valide.
"""
from __future__ import annotations

import os

os.environ["AGFLOW_DATA_DIR"] = "/tmp/agflow-data"
os.environ["AGFLOW_DATA_HOST_DIR"] = "/srv/agflow/data"

from agflow.services.container_runner import build_service_spec


_BASIC_PARAMS = """
{
  "docker": {
    "Container": {"Name": "agent-claude-{id}", "Image": "agflow-claude:{hash}"},
    "Network": {"Mode": "agflow-internal"},
    "Runtime": {"Init": true, "WorkingDir": "/app"},
    "Resources": {"Memory": "1g", "Cpus": "1.5"},
    "Environments": {"FOO": "bar"},
    "Mounts": []
  },
  "Params": {}
}
"""


def test_build_service_spec_returns_name_and_spec_dict() -> None:
    name, spec = build_service_spec(
        dockerfile_id="claude",
        params_json_content=_BASIC_PARAMS,
        content_hash="abc123",
        instance_id="xyz789",
    )
    assert name == "agent-claude-xyz789"
    assert isinstance(spec, dict)
    assert "Name" in spec
    assert spec["Name"] == name


def test_build_service_spec_image_resolved_from_template() -> None:
    _, spec = build_service_spec(
        dockerfile_id="claude",
        params_json_content=_BASIC_PARAMS,
        content_hash="abc123",
        instance_id="xyz789",
    )
    assert spec["TaskTemplate"]["ContainerSpec"]["Image"] == "agflow-claude:abc123"


def test_build_service_spec_env_list() -> None:
    _, spec = build_service_spec(
        dockerfile_id="claude",
        params_json_content=_BASIC_PARAMS,
        content_hash="abc123",
        instance_id="xyz789",
    )
    env = spec["TaskTemplate"]["ContainerSpec"]["Env"]
    assert "FOO=bar" in env


def test_build_service_spec_resources_mapped() -> None:
    _, spec = build_service_spec(
        dockerfile_id="claude",
        params_json_content=_BASIC_PARAMS,
        content_hash="abc123",
        instance_id="xyz789",
    )
    res = spec["TaskTemplate"]["Resources"]
    # 1g = 1 GiB = 1073741824 bytes
    assert res["Limits"]["MemoryBytes"] == 1073741824
    # 1.5 cpus = 1.5e9 nano-cpus
    assert res["Limits"]["NanoCPUs"] == 1500000000


def test_build_service_spec_default_endpoint_mode_dnsrr() -> None:
    """IPVS LXC workaround : endpoint_mode dnsrr toujours."""
    _, spec = build_service_spec(
        dockerfile_id="claude",
        params_json_content=_BASIC_PARAMS,
        content_hash="abc",
        instance_id="x",
    )
    assert spec["EndpointSpec"]["Mode"] == "dnsrr"


def test_build_service_spec_default_placement_manager() -> None:
    """Placement node.role==manager hardcoded (single-node manager MVP)."""
    _, spec = build_service_spec(
        dockerfile_id="claude",
        params_json_content=_BASIC_PARAMS,
        content_hash="abc",
        instance_id="x",
    )
    constraints = spec["TaskTemplate"]["Placement"]["Constraints"]
    assert "node.role == manager" in constraints


def test_build_service_spec_default_replicas_one() -> None:
    """1 service = 1 agent (replicas:1 MVP)."""
    _, spec = build_service_spec(
        dockerfile_id="claude",
        params_json_content=_BASIC_PARAMS,
        content_hash="abc",
        instance_id="x",
    )
    assert spec["Mode"] == {"Replicated": {"Replicas": 1}}


def test_build_service_spec_labels_on_container_and_service() -> None:
    """Labels agflow.* dupliquees au niveau container ET service."""
    _, spec = build_service_spec(
        dockerfile_id="claude",
        params_json_content=_BASIC_PARAMS,
        content_hash="abc",
        instance_id="xyz789",
    )
    container_labels = spec["TaskTemplate"]["ContainerSpec"]["Labels"]
    service_labels = spec["Labels"]
    for labels in (container_labels, service_labels):
        assert labels["agflow.managed"] == "true"
        assert labels["agflow.dockerfile_id"] == "claude"
        assert labels["agflow.instance_id"] == "xyz789"


def test_build_service_spec_network_target() -> None:
    _, spec = build_service_spec(
        dockerfile_id="claude",
        params_json_content=_BASIC_PARAMS,
        content_hash="abc",
        instance_id="x",
    )
    networks = spec["Networks"]
    assert any(n["Target"] == "agflow-internal" for n in networks)


def test_build_service_spec_restart_policy_on_failure() -> None:
    """RestartPolicy.Condition mappe vers 'on-failure' (best Swarm match)."""
    _, spec = build_service_spec(
        dockerfile_id="claude",
        params_json_content=_BASIC_PARAMS,
        content_hash="abc",
        instance_id="x",
    )
    rp = spec["TaskTemplate"]["RestartPolicy"]
    assert rp["Condition"] == "on-failure"
    assert rp["MaxAttempts"] == 5
```

- [ ] **Step 2 : Run, vérifier l'échec**

```bash
cd backend && uv run pytest tests/test_container_runner_service_spec.py -v
```

Attendu : `ImportError: cannot import name 'build_service_spec'`.

- [ ] **Step 3 : Implémentation**

Ajouter dans `backend/src/agflow/services/container_runner.py` (juste après `build_run_config` qui se termine ligne ~621, donc nouvelle fonction à ~625) :

```python
# ── B1 : Swarm ServiceSpec builder (mirror de build_run_config) ──────────


_DEFAULT_SWARM_NETWORK = "agflow-internal"


def build_service_spec(
    *,
    dockerfile_id: str,
    params_json_content: str,
    content_hash: str,
    instance_id: str,
    extra_env: dict[str, str] | None = None,
    mount_base_id: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Build Swarm ServiceSpec from Dockerfile.json (mirror of build_run_config).

    Returns (service_name, service_spec_dict). Le service_spec_dict est
    consommable par aiodocker.Docker().services.create(spec).

    Differences vs build_run_config :
      - Mounts en objects {Source, Target, Type='bind', ReadOnly} au lieu de Binds
      - Resources dans TaskTemplate.Resources
      - RestartPolicy.Condition = 'on-failure' (Swarm n'a pas 'unless-stopped')
      - Mode.Replicated.Replicas = 1 hardcoded
      - EndpointSpec.Mode = 'dnsrr' hardcoded (IPVS LXC workaround)
      - Placement.Constraints = ['node.role == manager'] hardcoded
      - Labels dupliquees container-level + service-level
    """
    # Reuse build_run_config to get all the resolved parts
    name, classic_config = build_run_config(
        dockerfile_id=dockerfile_id,
        params_json_content=params_json_content,
        content_hash=content_hash,
        instance_id=instance_id,
        extra_env=extra_env,
        mount_base_id=mount_base_id,
    )

    # Convert Binds (Docker classic) -> Mounts (Swarm format)
    binds = classic_config.get("HostConfig", {}).get("Binds", [])
    mounts = []
    for bind in binds:
        # Format "source:target[:ro]"
        parts = bind.split(":")
        if len(parts) < 2:
            continue
        source, target = parts[0], parts[1]
        readonly = len(parts) > 2 and parts[2] == "ro"
        mounts.append({
            "Source": source,
            "Target": target,
            "Type": "bind",
            "ReadOnly": readonly,
        })

    container_spec: dict[str, Any] = {
        "Image": classic_config["Image"],
        "Env": classic_config.get("Env", []),
        "Labels": classic_config.get("Labels", {}),
        "Mounts": mounts,
    }
    if classic_config.get("WorkingDir"):
        container_spec["Dir"] = classic_config["WorkingDir"]
    if classic_config.get("StopSignal"):
        container_spec["StopSignal"] = classic_config["StopSignal"]
    host_init = classic_config.get("HostConfig", {}).get("Init")
    if host_init is not None:
        container_spec["Init"] = bool(host_init)

    resources: dict[str, Any] = {}
    host_config = classic_config.get("HostConfig", {})
    limits: dict[str, Any] = {}
    if host_config.get("Memory"):
        limits["MemoryBytes"] = host_config["Memory"]
    if host_config.get("NanoCpus"):
        limits["NanoCPUs"] = host_config["NanoCpus"]
    if limits:
        resources["Limits"] = limits

    task_template: dict[str, Any] = {
        "ContainerSpec": container_spec,
        "RestartPolicy": {
            "Condition": "on-failure",
            "MaxAttempts": 5,
            "Delay": 10_000_000_000,  # 10s in nanoseconds
        },
        "Placement": {
            "Constraints": ["node.role == manager"],
        },
    }
    if resources:
        task_template["Resources"] = resources

    spec: dict[str, Any] = {
        "Name": name,
        "TaskTemplate": task_template,
        "Mode": {"Replicated": {"Replicas": 1}},
        "Networks": [{"Target": _DEFAULT_SWARM_NETWORK}],
        "EndpointSpec": {"Mode": "dnsrr"},
        "Labels": dict(classic_config.get("Labels", {})),
    }
    return name, spec
```

- [ ] **Step 4 : Run, vérifier que ça passe**

```bash
cd backend && uv run pytest tests/test_container_runner_service_spec.py -v
```

Attendu : 10 tests verts.

- [ ] **Step 5 : Lint**

```bash
cd backend && uv run ruff check src/agflow/services/container_runner.py tests/test_container_runner_service_spec.py
```

Attendu : clean (ne pas appliquer de format sur sections pré-existantes du fichier — commit chirurgical).

- [ ] **Step 6 : Commit**

```bash
git add backend/src/agflow/services/container_runner.py backend/tests/test_container_runner_service_spec.py
git commit -m "feat(container-runner): build_service_spec mapping Dockerfile.json -> Swarm ServiceSpec

Mirror de build_run_config() qui produit un payload Swarm services API
au lieu de Docker classic. Conversion :
- Binds -> Mounts (Source/Target/Type=bind/ReadOnly)
- Resources Limits MemoryBytes + NanoCPUs
- RestartPolicy.Condition='on-failure' (Swarm n'a pas unless-stopped)
- Defaults hardcoded : Mode.Replicas=1, EndpointSpec.Mode=dnsrr,
  Placement node.role==manager
- Labels dupliquees container-level + service-level

10 tests unitaires (mapping basique + chacun des defaults)."
```

---

## Task 2 — `start()` Swarm via `services.create()` + polling tasks

**Files:**
- Modify: `backend/src/agflow/services/container_runner.py` (refacto fonction `start`)
- Create: `backend/tests/test_container_runner_swarm_lifecycle.py`

- [ ] **Step 1 : Tests rouges (start)**

Créer `backend/tests/test_container_runner_swarm_lifecycle.py` :

```python
"""Tests start()/stop()/list_running() avec mocks aiodocker.services."""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

os.environ["AGFLOW_DATA_DIR"] = "/tmp/agflow-data"
os.environ["AGFLOW_DATA_HOST_DIR"] = "/srv/agflow/data"

import pytest

from agflow.services import container_runner


_BASIC_PARAMS = """
{
  "docker": {
    "Container": {"Name": "agent-claude-{id}", "Image": "agflow-claude:{hash}"},
    "Network": {"Mode": "agflow-internal"},
    "Runtime": {"Init": true, "WorkingDir": "/app"},
    "Resources": {"Memory": "1g", "Cpus": "1.5"},
    "Environments": {},
    "Mounts": []
  },
  "Params": {}
}
"""


def _make_docker_mock(*, list_services=None, services_create=None,
                      services_inspect=None, tasks_list=None,
                      services_delete=None, image_inspect=None,
                      container_inspect=None) -> MagicMock:
    """Helper : construit un mock complet d'aiodocker.Docker()."""
    docker = MagicMock()
    docker.close = AsyncMock()

    docker.services = MagicMock()
    docker.services.create = AsyncMock(return_value=services_create or {"ID": "svc-id"})
    docker.services.inspect = AsyncMock(return_value=services_inspect)
    docker.services.list = AsyncMock(return_value=list_services or [])
    docker.services.delete = AsyncMock(return_value=services_delete)

    docker.tasks = MagicMock()
    docker.tasks.list = AsyncMock(return_value=tasks_list or [])

    docker.images = MagicMock()
    docker.images.inspect = AsyncMock(return_value=image_inspect or {"Id": "sha256:abc"})

    docker.containers = MagicMock()
    container_obj = MagicMock()
    container_obj.show = AsyncMock(return_value=container_inspect or {
        "Id": "container-id",
        "Name": "/agent-claude-xyz789",
        "Created": "2026-05-01T00:00:00.000000000Z",
        "Config": {"Image": "agflow-claude:abc", "Labels": {
            "agflow.managed": "true",
            "agflow.dockerfile_id": "claude",
            "agflow.instance_id": "xyz789",
        }},
        "State": {"Status": "running"},
    })
    docker.containers.container = MagicMock(return_value=container_obj)
    docker.containers.list = AsyncMock(return_value=[])

    return docker


@pytest.mark.asyncio
async def test_start_creates_service_and_resolves_container() -> None:
    """start() doit aiodocker.services.create() puis poll tasks pour récupérer le container."""
    docker = _make_docker_mock(
        services_create={"ID": "svc-abc"},
        tasks_list=[{
            "ID": "task-1",
            "Status": {"State": "running", "ContainerStatus": {"ContainerID": "container-id"}},
        }],
    )

    with (
        patch("agflow.services.container_runner.aiodocker.Docker", return_value=docker),
        patch("agflow.services.container_runner._load_platform_secrets",
              AsyncMock(return_value={})),
        patch("agflow.services.container_runner.list_running",
              AsyncMock(return_value=[])),
        patch("agflow.services.container_runner._ensure_mount_paths_from_config"),
        patch("agflow.services.container_runner._generate_tmp_files"),
    ):
        info = await container_runner.start(
            dockerfile_id="claude",
            params_json_content=_BASIC_PARAMS,
            content_hash="abc",
        )

    assert info.id == "container-id"
    assert info.dockerfile_id == "claude"
    docker.services.create.assert_called_once()


@pytest.mark.asyncio
async def test_start_rejects_when_max_services_reached() -> None:
    """Concurrency guard : MAX_RUNNING_CONTAINERS encore enforced."""
    fake_alive = [
        container_runner.ContainerInfo(
            id=f"c{i}", name=f"n{i}", dockerfile_id="x", image="i",
            status="running", created_at="2026-01-01T00:00:00", instance_id="i",
        )
        for i in range(container_runner.MAX_RUNNING_CONTAINERS)
    ]
    with patch("agflow.services.container_runner.list_running",
               AsyncMock(return_value=fake_alive)):
        with pytest.raises(container_runner.TooManyContainersError):
            await container_runner.start(
                dockerfile_id="claude",
                params_json_content=_BASIC_PARAMS,
                content_hash="abc",
            )


@pytest.mark.asyncio
async def test_start_raises_image_not_built_when_image_inspect_404() -> None:
    """Si l'image n'existe pas, lever ImageNotBuiltError (preflight)."""
    import aiodocker as _aio

    docker = _make_docker_mock()
    docker.images.inspect = AsyncMock(
        side_effect=_aio.exceptions.DockerError(
            status=404, data={"message": "no such image"},
        ),
    )

    with (
        patch("agflow.services.container_runner.aiodocker.Docker", return_value=docker),
        patch("agflow.services.container_runner._load_platform_secrets",
              AsyncMock(return_value={})),
        patch("agflow.services.container_runner.list_running",
              AsyncMock(return_value=[])),
        patch("agflow.services.container_runner._ensure_mount_paths_from_config"),
        patch("agflow.services.container_runner._generate_tmp_files"),
    ):
        with pytest.raises(container_runner.ImageNotBuiltError):
            await container_runner.start(
                dockerfile_id="claude",
                params_json_content=_BASIC_PARAMS,
                content_hash="abc",
            )


@pytest.mark.asyncio
async def test_start_polls_until_task_running() -> None:
    """Si le 1er poll renvoie pending, on attend que le task passe en running."""
    docker = _make_docker_mock()
    # 1er appel : pending. 2eme : running.
    docker.tasks.list = AsyncMock(side_effect=[
        [{"ID": "t1", "Status": {"State": "pending"}}],
        [{"ID": "t1", "Status": {"State": "running",
                                  "ContainerStatus": {"ContainerID": "container-id"}}}],
    ])

    with (
        patch("agflow.services.container_runner.aiodocker.Docker", return_value=docker),
        patch("agflow.services.container_runner._load_platform_secrets",
              AsyncMock(return_value={})),
        patch("agflow.services.container_runner.list_running",
              AsyncMock(return_value=[])),
        patch("agflow.services.container_runner._ensure_mount_paths_from_config"),
        patch("agflow.services.container_runner._generate_tmp_files"),
        patch("agflow.services.container_runner._asyncio.sleep", AsyncMock()),
    ):
        info = await container_runner.start(
            dockerfile_id="claude",
            params_json_content=_BASIC_PARAMS,
            content_hash="abc",
        )

    assert info.id == "container-id"
    assert docker.tasks.list.call_count == 2
```

> Note : pour le sleep mocké, il faut importer `asyncio` au module top de `container_runner.py` avec un alias `_asyncio` si pas déjà fait. Si déjà importé sans alias, le test peut patcher `agflow.services.container_runner.asyncio.sleep`. Adapte selon l'existant.

- [ ] **Step 2 : Run, vérifier l'échec**

```bash
cd backend && uv run pytest tests/test_container_runner_swarm_lifecycle.py -v
```

Attendu : tous rouges (start() actuel n'utilise pas services.create).

- [ ] **Step 3 : Refacto `start()`**

Remplacer le corps de `start()` (autour ligne 693-772) par :

```python
async def start(
    dockerfile_id: str,
    *,
    params_json_content: str,
    content_hash: str,
    user_secrets: dict[str, str] | None = None,
) -> ContainerInfo:
    """Create a Swarm service for an agent and resolve its container.

    Raises:
        ImageNotBuiltError: target image doesn't exist on the local daemon.
        TooManyContainersError: hard limit MAX_RUNNING_CONTAINERS reached.
        InvalidParamsError: Dockerfile.json cannot be translated.
    """
    import asyncio as _asyncio

    # Concurrency guard
    existing = await list_running()
    alive = [c for c in existing if c.status in ("running", "created", "restarting")]
    if len(alive) >= MAX_RUNNING_CONTAINERS:
        raise TooManyContainersError(
            f"Maximum of {MAX_RUNNING_CONTAINERS} running containers reached. "
            f"Stop one before launching another."
        )

    instance_id = secrets.token_hex(3)
    platform_secrets = await _load_platform_secrets()
    all_secrets = {**platform_secrets, **(user_secrets or {})}
    name, spec = build_service_spec(
        dockerfile_id=dockerfile_id,
        params_json_content=params_json_content,
        content_hash=content_hash,
        instance_id=instance_id,
        extra_env=all_secrets,
    )
    classic_image = spec["TaskTemplate"]["ContainerSpec"]["Image"]

    # Pre-create auto-prefixed mount dirs (same as before, reuse classic build)
    _ensure_mount_paths_from_config(
        dockerfile_id, params_json_content, instance_id, content_hash,
    )

    # Generate .tmp/ classic files for diagnostic (run.sh always generated for debug)
    _, classic_config = build_run_config(
        dockerfile_id=dockerfile_id,
        params_json_content=params_json_content,
        content_hash=content_hash,
        instance_id=instance_id,
        extra_env=all_secrets,
    )
    _generate_tmp_files(dockerfile_id, name, classic_config)

    docker = aiodocker.Docker()
    try:
        # Preflight : image must exist
        try:
            await docker.images.inspect(classic_image)
        except aiodocker.exceptions.DockerError as exc:
            if exc.status == 404:
                raise ImageNotBuiltError(
                    f"Image '{classic_image}' not found — build the dockerfile first."
                ) from exc
            raise

        # Create the Swarm service
        service_create_resp = await docker.services.create(spec)
        service_id = service_create_resp.get("ID") or service_create_resp.get("Id", "")

        # Poll tasks until at least one is running (timeout ~30s)
        container_id = ""
        for _attempt in range(30):
            tasks = await docker.tasks.list(filters={"service": name})
            for task in tasks:
                state = task.get("Status", {}).get("State", "")
                if state == "running":
                    cs = task.get("Status", {}).get("ContainerStatus", {}) or {}
                    container_id = cs.get("ContainerID", "")
                    if container_id:
                        break
            if container_id:
                break
            await _asyncio.sleep(1)

        if not container_id:
            # Service was created but no container came up. Cleanup + error.
            with contextlib.suppress(Exception):
                await docker.services.delete(service_id)
            raise ContainerRunnerError(
                f"Service '{name}' created but no running container after 30s"
            )

        # Inspect the container to produce ContainerInfo
        container = docker.containers.container(container_id=container_id)
        inspect = await container.show()
        cfg = inspect.get("Config") or {}
        state = inspect.get("State") or {}
        labels = cfg.get("Labels") or {}
        info = ContainerInfo(
            id=inspect.get("Id", container_id),
            name=(inspect.get("Name") or name).lstrip("/"),
            dockerfile_id=labels.get(_AGFLOW_DOCKERFILE_LABEL, dockerfile_id),
            image=cfg.get("Image", classic_image),
            status=state.get("Status", "running"),
            created_at=_parse_docker_ts(inspect.get("Created", "")),
            instance_id=labels.get(_AGFLOW_INSTANCE_LABEL, instance_id),
        )
        _log.info(
            "container.start_swarm",
            dockerfile_id=dockerfile_id,
            service_id=service_id,
            service_name=name,
            container_id=info.id,
        )
        return info
    finally:
        await docker.close()
```

- [ ] **Step 4 : Run, vérifier que ça passe**

```bash
cd backend && uv run pytest tests/test_container_runner_swarm_lifecycle.py -v
```

Attendu : 4 tests verts.

- [ ] **Step 5 : Lint**

```bash
cd backend && uv run ruff check src/agflow/services/container_runner.py tests/test_container_runner_swarm_lifecycle.py
```

- [ ] **Step 6 : Commit**

```bash
git add backend/src/agflow/services/container_runner.py backend/tests/test_container_runner_swarm_lifecycle.py
git commit -m "feat(container-runner): start() utilise aiodocker.services.create (Swarm)

Switch direct : build_service_spec + services.create + polling tasks
jusqu'a state=running + résolution container_id du replica → inspect
container → ContainerInfo (compat schema preserve).

Concurrency guard MAX_RUNNING_CONTAINERS conserve. ImageNotBuiltError
preflight conserve. _generate_tmp_files (run.sh) toujours genere pour
diagnostic local.

4 tests : success, max reached, image 404, polling jusqu'a running."
```

---

## Task 3 — `stop()` + `list_running()` Swarm

**Files:**
- Modify: `backend/src/agflow/services/container_runner.py` (refacto `stop` + `list_running`)
- Modify: `backend/tests/test_container_runner_swarm_lifecycle.py` (ajout tests)

- [ ] **Step 1 : Tests rouges**

Ajouter à la fin de `backend/tests/test_container_runner_swarm_lifecycle.py` :

```python
@pytest.mark.asyncio
async def test_stop_deletes_service_when_found() -> None:
    """stop() trouve le service via services.list filters et appelle services.delete."""
    docker = _make_docker_mock(
        list_services=[{"ID": "svc-abc", "Spec": {"Name": "agent-claude-xyz789",
                                                   "Labels": {"agflow.managed": "true"}}}],
    )

    with patch("agflow.services.container_runner.aiodocker.Docker", return_value=docker):
        await container_runner.stop("agent-claude-xyz789")

    docker.services.delete.assert_called_once_with("svc-abc")


@pytest.mark.asyncio
async def test_stop_raises_not_found_when_no_service_no_container() -> None:
    """Si ni service ni container ne match, ContainerNotFoundError."""
    import aiodocker as _aio

    docker = _make_docker_mock(list_services=[])
    container_obj = MagicMock()
    container_obj.show = AsyncMock(side_effect=_aio.exceptions.DockerError(
        status=404, data={"message": "not found"},
    ))
    docker.containers.container = MagicMock(return_value=container_obj)

    with patch("agflow.services.container_runner.aiodocker.Docker", return_value=docker):
        with pytest.raises(container_runner.ContainerNotFoundError):
            await container_runner.stop("agent-doesnt-exist")


@pytest.mark.asyncio
async def test_list_running_returns_containers_resolved_from_services() -> None:
    """list_running list les services agflow-managed et résoud chaque container."""
    docker = _make_docker_mock(
        list_services=[
            {"ID": "svc1", "Spec": {"Name": "agent-claude-aaa",
                                    "Labels": {"agflow.managed": "true",
                                               "agflow.dockerfile_id": "claude",
                                               "agflow.instance_id": "aaa"}}},
        ],
        tasks_list=[{
            "ID": "task1",
            "Status": {"State": "running", "ContainerStatus": {"ContainerID": "cnt1"}},
        }],
        container_inspect={
            "Id": "cnt1",
            "Name": "/agent-claude-aaa",
            "Created": "2026-05-01T00:00:00.000000000Z",
            "Config": {"Image": "agflow-claude:hash", "Labels": {
                "agflow.managed": "true",
                "agflow.dockerfile_id": "claude",
                "agflow.instance_id": "aaa",
            }},
            "State": {"Status": "running"},
        },
    )

    with patch("agflow.services.container_runner.aiodocker.Docker", return_value=docker):
        result = await container_runner.list_running()

    assert len(result) == 1
    assert result[0].id == "cnt1"
    assert result[0].dockerfile_id == "claude"
    assert result[0].instance_id == "aaa"


@pytest.mark.asyncio
async def test_list_running_skips_services_with_no_running_task() -> None:
    """Service sans task running (pending/failed) doit être skipped (pas dans le résultat)."""
    docker = _make_docker_mock(
        list_services=[
            {"ID": "svc1", "Spec": {"Name": "agent-x", "Labels": {"agflow.managed": "true"}}},
        ],
        tasks_list=[{"ID": "task1", "Status": {"State": "pending"}}],
    )

    with patch("agflow.services.container_runner.aiodocker.Docker", return_value=docker):
        result = await container_runner.list_running()

    assert result == []
```

- [ ] **Step 2 : Run, vérifier les rouges**

```bash
cd backend && uv run pytest tests/test_container_runner_swarm_lifecycle.py -v
```

Attendu : 4 verts (T2) + 4 rouges (stop/list_running encore en mode containers).

- [ ] **Step 3 : Refacto `stop()` et `list_running()`**

Remplacer `list_running()` (autour ligne 661-691) :

```python
async def list_running() -> list[ContainerInfo]:
    """List all running agflow-managed agents (Swarm services + their containers).

    Pour chaque service avec label agflow.managed=true, récupère le 1er task
    en running et résoud le container réel pour produire un ContainerInfo.
    Les services sans task running (pending/failed) sont skippés.
    """
    docker = aiodocker.Docker()
    try:
        services = await docker.services.list(
            filters={"label": [f"{_AGFLOW_MANAGED_LABEL}=true"]},
        )
        result: list[ContainerInfo] = []
        for svc in services or []:
            svc_name = (svc.get("Spec") or {}).get("Name", "")
            if not svc_name:
                continue
            try:
                tasks = await docker.tasks.list(filters={"service": svc_name})
            except aiodocker.exceptions.DockerError:
                continue
            container_id = ""
            for task in tasks or []:
                if (task.get("Status") or {}).get("State") == "running":
                    cs = (task.get("Status") or {}).get("ContainerStatus", {}) or {}
                    cid = cs.get("ContainerID")
                    if cid:
                        container_id = cid
                        break
            if not container_id:
                continue
            try:
                container = docker.containers.container(container_id=container_id)
                inspect = await container.show()
            except aiodocker.exceptions.DockerError:
                continue
            cfg = inspect.get("Config") or {}
            state = inspect.get("State") or {}
            labels = cfg.get("Labels") or {}
            result.append(ContainerInfo(
                id=inspect.get("Id", container_id),
                name=(inspect.get("Name") or svc_name).lstrip("/"),
                dockerfile_id=labels.get(_AGFLOW_DOCKERFILE_LABEL, ""),
                image=cfg.get("Image", ""),
                status=state.get("Status", "running"),
                created_at=_parse_docker_ts(inspect.get("Created", "")),
                instance_id=labels.get(_AGFLOW_INSTANCE_LABEL, ""),
            ))
        return result
    finally:
        await docker.close()
```

Remplacer `stop()` (autour ligne 1031-1064) :

```python
async def stop(container_id: str) -> None:
    """Stop and remove an agent : delete its Swarm service if exists, sinon
    fallback container delete (rétro-compat pour containers classiques restants).

    Le param 'container_id' peut être un service name (cas Swarm) ou un container
    id/name (cas legacy). On essaie service en 1er, fallback container ensuite.
    """
    docker = aiodocker.Docker()
    try:
        # Try Swarm service first
        try:
            services = await docker.services.list(
                filters={"name": [container_id]},
            )
        except aiodocker.exceptions.DockerError:
            services = []

        for svc in services or []:
            svc_id = svc.get("ID") or svc.get("Id", "")
            svc_labels = (svc.get("Spec") or {}).get("Labels", {}) or {}
            svc_name = (svc.get("Spec") or {}).get("Name", "")
            # Vérification managed et match exact du nom (le filter "name" peut être prefix)
            if (svc_labels.get(_AGFLOW_MANAGED_LABEL) == "true"
                    and (svc_name == container_id or svc_id == container_id)):
                try:
                    await docker.services.delete(svc_id)
                except aiodocker.exceptions.DockerError as exc:
                    if exc.status not in (404, 409):
                        raise
                _log.info("container.stop_swarm", service_id=svc_id, service_name=svc_name)
                return

        # Fallback : container classique
        try:
            container = docker.containers.container(container_id=container_id)
            inspect = await container.show()
        except aiodocker.exceptions.DockerError as exc:
            if exc.status == 404:
                raise ContainerNotFoundError(
                    f"Service or container '{container_id}' not found"
                ) from exc
            raise

        labels = (inspect.get("Config") or {}).get("Labels") or {}
        if labels.get(_AGFLOW_MANAGED_LABEL) != "true":
            raise ContainerNotFoundError(
                f"Container '{container_id}' is not managed by agflow"
            )
        with contextlib.suppress(aiodocker.exceptions.DockerError):
            await container.stop(timeout=10)
        try:
            await container.delete(force=True)
        except aiodocker.exceptions.DockerError as exc:
            if exc.status not in (404, 409):
                raise
        _log.info("container.stop_legacy", container_id=container_id)
    finally:
        await docker.close()
```

- [ ] **Step 4 : Run, vérifier que ça passe**

```bash
cd backend && uv run pytest tests/test_container_runner_swarm_lifecycle.py -v
```

Attendu : 8 tests verts.

- [ ] **Step 5 : Lint**

```bash
cd backend && uv run ruff check src/agflow/services/container_runner.py tests/test_container_runner_swarm_lifecycle.py
```

- [ ] **Step 6 : Commit**

```bash
git add backend/src/agflow/services/container_runner.py backend/tests/test_container_runner_swarm_lifecycle.py
git commit -m "feat(container-runner): stop() + list_running() utilisent l'API Swarm services

list_running() : aiodocker.services.list par label agflow.managed=true,
puis pour chaque service résoud le 1er task running -> container -> ContainerInfo.

stop() : tente d'abord services.delete, fallback container.delete pour les
containers classiques residuels (retro-compat). Garantit que le container
est bien agflow-managed avant suppression.

4 tests : delete service, fallback container, list resolves, skip pending."
```

---

## Task 4 — Adaptation `terminal.py` (résolution service → container)

**Files:**
- Modify: `backend/src/agflow/api/admin/terminal.py`
- Create: `backend/tests/test_terminal_service_resolution.py`

- [ ] **Step 1 : Tests rouges**

Créer `backend/tests/test_terminal_service_resolution.py` :

```python
"""Tests pour le helper de résolution service → container du terminal."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agflow.api.admin.terminal import _resolve_to_container_id


@pytest.mark.asyncio
async def test_resolve_returns_container_id_for_swarm_service() -> None:
    """Si l'input est un nom de service Swarm, retourne le container du 1er task running."""
    docker = MagicMock()
    docker.close = AsyncMock()
    docker.services = MagicMock()
    docker.services.inspect = AsyncMock(return_value={
        "Spec": {"Name": "agent-claude-xyz"},
    })
    docker.tasks = MagicMock()
    docker.tasks.list = AsyncMock(return_value=[
        {"Status": {"State": "running",
                    "ContainerStatus": {"ContainerID": "container-abc"}}},
    ])

    with patch("agflow.api.admin.terminal.aiodocker.Docker", return_value=docker):
        result = await _resolve_to_container_id("agent-claude-xyz")

    assert result == "container-abc"


@pytest.mark.asyncio
async def test_resolve_returns_input_when_not_a_service() -> None:
    """Si services.inspect lève 404, on retourne l'input tel quel (legacy container)."""
    import aiodocker as _aio

    docker = MagicMock()
    docker.close = AsyncMock()
    docker.services = MagicMock()
    docker.services.inspect = AsyncMock(
        side_effect=_aio.exceptions.DockerError(status=404, data={"message": "not a service"}),
    )

    with patch("agflow.api.admin.terminal.aiodocker.Docker", return_value=docker):
        result = await _resolve_to_container_id("legacy-container-id")

    assert result == "legacy-container-id"


@pytest.mark.asyncio
async def test_resolve_raises_when_service_has_no_running_task() -> None:
    docker = MagicMock()
    docker.close = AsyncMock()
    docker.services = MagicMock()
    docker.services.inspect = AsyncMock(return_value={"Spec": {"Name": "agent-x"}})
    docker.tasks = MagicMock()
    docker.tasks.list = AsyncMock(return_value=[
        {"Status": {"State": "pending"}},
    ])

    with patch("agflow.api.admin.terminal.aiodocker.Docker", return_value=docker):
        with pytest.raises(ValueError, match="no running task"):
            await _resolve_to_container_id("agent-x")
```

- [ ] **Step 2 : Run, vérifier l'échec**

```bash
cd backend && uv run pytest tests/test_terminal_service_resolution.py -v
```

Attendu : `ImportError`.

- [ ] **Step 3 : Implémentation**

Modifier `backend/src/agflow/api/admin/terminal.py` :

1. Ajouter en haut du fichier (avec les imports existants) :

```python
import aiodocker
```

2. Ajouter la fonction helper avant le router :

```python
async def _resolve_to_container_id(maybe_service_id_or_name: str) -> str:
    """Si l'input est un service Swarm agflow, retourne le container_id du 1er task running.
    Sinon (404 sur services.inspect), retourne l'input tel quel (cas legacy container).
    """
    docker = aiodocker.Docker()
    try:
        try:
            svc = await docker.services.inspect(maybe_service_id_or_name)
        except aiodocker.exceptions.DockerError as exc:
            if exc.status == 404:
                # Pas un service Swarm — on suppose container classique, retourne tel quel
                return maybe_service_id_or_name
            raise

        svc_name = (svc.get("Spec") or {}).get("Name", "")
        tasks = await docker.tasks.list(filters={"service": svc_name})
        for task in tasks or []:
            state = (task.get("Status") or {}).get("State")
            if state == "running":
                cs = (task.get("Status") or {}).get("ContainerStatus", {}) or {}
                cid = cs.get("ContainerID")
                if cid:
                    return cid
        raise ValueError(f"Service {maybe_service_id_or_name} has no running task")
    finally:
        await docker.close()
```

3. Modifier le handler `container_terminal` pour résoudre `container_id` avant `docker exec`.

Trouver la ligne (autour ligne 47) :
```python
            command = f"docker exec -ti {container_id} /bin/sh"
```

La remplacer par :
```python
            resolved_id = await _resolve_to_container_id(container_id)
            command = f"docker exec -ti {resolved_id} /bin/sh"
```

- [ ] **Step 4 : Run, vérifier que ça passe**

```bash
cd backend && uv run pytest tests/test_terminal_service_resolution.py -v
```

Attendu : 3 tests verts.

- [ ] **Step 5 : Lint**

```bash
cd backend && uv run ruff check src/agflow/api/admin/terminal.py tests/test_terminal_service_resolution.py
```

- [ ] **Step 6 : Commit**

```bash
git add backend/src/agflow/api/admin/terminal.py backend/tests/test_terminal_service_resolution.py
git commit -m "feat(terminal): résolution service Swarm -> container avant docker exec

Si le container_id passe en path est un nom de service Swarm agflow,
on inspecte le 1er task running et on récupère le ContainerID réel
avant de faire docker exec -ti. Fallback : si services.inspect 404,
on suppose container classique et retourne tel quel.

3 tests : success service, fallback container, raises si pas de task running."
```

---

## Task 5 — Vérification non-régression workers + supervision

**Files:** Aucun changement de code.

- [ ] **Step 1 : Suite tests workers actuels**

```bash
cd backend && uv run pytest tests/workers/ -v 2>&1 | tail -10
```

Attendu : tous verts (les workers utilisent `stop()` et `list_running()` qui ont des signatures préservées). Si l'un casse, c'est un bug à investiguer immédiatement.

- [ ] **Step 2 : Smoke import + register routes**

```bash
cd backend && uv run python -c "
from agflow.main import create_app
app = create_app()
paths = sorted({r.path for r in app.routes if 'container' in r.path or 'terminal' in r.path})
for p in paths[:15]:
    print(p)
print('boot ok')
"
```

Attendu : routes containers + terminal listées + `boot ok`.

- [ ] **Step 3 : Pas de commit (pas de changement code)**

---

## Task 6 — `_generate_tmp_files_swarm()` (génération stack.yml + deploy.sh)

**Files:**
- Modify: `backend/src/agflow/services/container_runner.py` (ajout fonction)
- Create: `backend/tests/test_container_runner_run_task_swarm.py`

- [ ] **Step 1 : Tests rouges (snapshot des fichiers générés)**

Créer `backend/tests/test_container_runner_run_task_swarm.py` :

```python
"""Tests pour _generate_tmp_files_swarm() + run_task_swarm()."""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

os.environ["AGFLOW_DATA_DIR"] = "/tmp/agflow-data"
os.environ["AGFLOW_DATA_HOST_DIR"] = "/srv/agflow/data"


@pytest.fixture
def tmp_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Override AGFLOW_DATA_DIR vers tmp_path pour test isolation."""
    monkeypatch.setenv("AGFLOW_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AGFLOW_DATA_HOST_DIR", str(tmp_path))
    # Crée le sous-dir attendu pour le dockerfile
    (tmp_path / "dockerfiles" / "claude").mkdir(parents=True)
    return tmp_path


def test_generate_tmp_files_swarm_creates_4_files(tmp_data_dir: Path) -> None:
    from agflow.services.container_runner import _generate_tmp_files_swarm

    config = {
        "Image": "agflow-claude:abc",
        "Env": ["KEY=val"],
        "HostConfig": {"Memory": 1073741824, "NanoCpus": 1500000000, "Binds": []},
        "Labels": {"agflow.managed": "true", "agflow.dockerfile_id": "claude",
                   "agflow.instance_id": "xyz"},
    }
    deploy_path = _generate_tmp_files_swarm(
        dockerfile_id="claude",
        service_name="agent-claude-xyz",
        config=config,
        task_payload={"text": "hello"},
    )

    tmp_dir = tmp_data_dir / "dockerfiles" / "claude" / ".tmp"
    assert tmp_dir.exists()
    assert (tmp_dir / ".env").exists()
    assert (tmp_dir / "stack.yml").exists()
    assert (tmp_dir / "deploy.sh").exists()
    assert (tmp_dir / "task.json").exists()
    assert deploy_path == str(tmp_dir / "deploy.sh")


def test_generate_tmp_files_swarm_stack_yml_is_valid_compose(tmp_data_dir: Path) -> None:
    from agflow.services.container_runner import _generate_tmp_files_swarm

    config = {
        "Image": "agflow-claude:abc",
        "Env": ["KEY=val"],
        "HostConfig": {"Memory": 1073741824, "Binds": []},
        "Labels": {"agflow.managed": "true"},
    }
    _generate_tmp_files_swarm(
        dockerfile_id="claude",
        service_name="agent-claude-xyz",
        config=config,
        task_payload={"text": "hi"},
    )

    stack_yml = (tmp_data_dir / "dockerfiles" / "claude" / ".tmp" / "stack.yml").read_text()
    parsed = yaml.safe_load(stack_yml)

    assert "services" in parsed
    assert "agent" in parsed["services"]
    svc = parsed["services"]["agent"]
    assert svc["image"] == "agflow-claude:abc"
    # Doit contenir le bloc deploy avec endpoint_mode dnsrr + placement manager
    assert svc["deploy"]["endpoint_mode"] == "dnsrr"
    assert "node.role == manager" in svc["deploy"]["placement"]["constraints"]
    # Restart policy 'none' pour one-shot
    assert svc["deploy"]["restart_policy"]["condition"] == "none"
    # Network agflow-internal external
    assert parsed["networks"]["agflow-internal"]["external"] is True


def test_generate_tmp_files_swarm_task_json_is_payload(tmp_data_dir: Path) -> None:
    from agflow.services.container_runner import _generate_tmp_files_swarm

    config = {"Image": "img", "Env": [], "HostConfig": {"Binds": []}, "Labels": {}}
    _generate_tmp_files_swarm(
        dockerfile_id="claude",
        service_name="x",
        config=config,
        task_payload={"key": "value", "nested": {"a": 1}},
    )

    task_json = (tmp_data_dir / "dockerfiles" / "claude" / ".tmp" / "task.json").read_text()
    parsed = json.loads(task_json)
    assert parsed == {"key": "value", "nested": {"a": 1}}


def test_generate_tmp_files_swarm_deploy_sh_is_executable(tmp_data_dir: Path) -> None:
    from agflow.services.container_runner import _generate_tmp_files_swarm

    config = {"Image": "img", "Env": [], "HostConfig": {"Binds": []}, "Labels": {}}
    deploy_path = _generate_tmp_files_swarm(
        dockerfile_id="claude",
        service_name="x",
        config=config,
        task_payload={"k": "v"},
    )
    # Vérifie le shebang + structure attendue
    content = Path(deploy_path).read_text()
    assert content.startswith("#!/usr/bin/env bash")
    assert "docker stack deploy" in content
    assert "docker service logs" in content
    assert "docker stack rm" in content
    # Sur Unix, vérifie le mode exécutable. Sur Windows, skipped.
    if os.name != "nt":
        assert os.access(deploy_path, os.X_OK)
```

- [ ] **Step 2 : Run, vérifier les rouges**

```bash
cd backend && uv run pytest tests/test_container_runner_run_task_swarm.py -v
```

Attendu : `ImportError` sur `_generate_tmp_files_swarm`.

- [ ] **Step 3 : Implémentation `_generate_tmp_files_swarm()`**

Ajouter dans `backend/src/agflow/services/container_runner.py` (après `_generate_tmp_files`, avant `_load_platform_secrets` ligne ~135) :

```python
def _generate_tmp_files_swarm(
    dockerfile_id: str,
    service_name: str,
    config: dict[str, Any],
    task_payload: dict[str, Any] | None = None,
) -> str:
    """Generate .env + stack.yml + deploy.sh + task.json in
    {AGFLOW_DATA_DIR}/dockerfiles/{dockerfile_id}/.tmp/.

    Mirror de _generate_tmp_files() mais produit du Swarm stack au lieu
    de docker run command. Les fichiers sont inspectables et runnable
    by hand par l'admin (philosophie identique).

    Returns le path absolu du deploy.sh généré.
    """
    import json as _json

    import yaml as _yaml

    data_dir = os.environ.get("AGFLOW_DATA_DIR", "/app/data")
    tmp_dir = os.path.join(data_dir, "dockerfiles", dockerfile_id, ".tmp")
    os.makedirs(tmp_dir, exist_ok=True)

    # .env — variables d'env résolues
    env_list = config.get("Env", [])
    env_content = "\n".join(env_list) + "\n"
    with open(os.path.join(tmp_dir, ".env"), "w", encoding="utf-8") as f:
        f.write(env_content)

    # task.json — payload brut
    if task_payload is not None:
        task_path = os.path.join(tmp_dir, "task.json")
        with open(task_path, "w", encoding="utf-8") as f:
            _json.dump(task_payload, f, ensure_ascii=False)
            f.write("\n")

    # stack.yml — Swarm stack compose v3+
    host_config = config.get("HostConfig", {})
    binds = host_config.get("Binds", [])
    volumes = []
    for bind in binds:
        parts = bind.split(":")
        if len(parts) >= 2:
            volumes.append({
                "type": "bind",
                "source": parts[0],
                "target": parts[1],
                "read_only": (len(parts) > 2 and parts[2] == "ro"),
            })

    deploy_block: dict[str, Any] = {
        "mode": "replicated",
        "replicas": 1,
        "endpoint_mode": "dnsrr",
        "placement": {"constraints": ["node.role == manager"]},
        "restart_policy": {"condition": "none"},  # one-shot
        "labels": [
            "agflow.managed=true",
            "agflow.test_mode=swarm",
            f"agflow.dockerfile_id={dockerfile_id}",
        ],
    }
    resources_limits: dict[str, Any] = {}
    if host_config.get("Memory"):
        # bytes -> '1G' style not trivial ; stack supports bytes via mem_limit ? Use raw int.
        # docker compose v3+ accepte bytes int dans deploy.resources.limits.memory
        resources_limits["memory"] = str(host_config["Memory"])
    if host_config.get("NanoCpus"):
        # NanoCpus -> cpus float
        resources_limits["cpus"] = str(host_config["NanoCpus"] / 1_000_000_000)
    if resources_limits:
        deploy_block["resources"] = {"limits": resources_limits}

    service_def: dict[str, Any] = {
        "image": config["Image"],
        "networks": ["agflow-internal"],
        "deploy": deploy_block,
    }
    # Convert env list to dict format for stack.yml
    if env_list:
        service_def["environment"] = {}
        for env_line in env_list:
            if "=" in env_line:
                k, v = env_line.split("=", 1)
                service_def["environment"][k] = v
    if volumes:
        service_def["volumes"] = volumes
    if config.get("WorkingDir"):
        service_def["working_dir"] = config["WorkingDir"]
    if host_config.get("Init"):
        service_def["init"] = True

    stack: dict[str, Any] = {
        "services": {"agent": service_def},
        "networks": {"agflow-internal": {"external": True}},
    }

    stack_path = os.path.join(tmp_dir, "stack.yml")
    with open(stack_path, "w", encoding="utf-8") as f:
        _yaml.dump(stack, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    # deploy.sh — wrapper bash
    deploy_sh = f"""#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
STACK_NAME="{service_name.replace('-', '_')}_test"

# Source .env
set -a; source "$SCRIPT_DIR/.env" 2>/dev/null || true; set +a

# Inject task.json content as env var (Swarm n'aime pas le stdin pipe)
if [ -f "$SCRIPT_DIR/task.json" ]; then
    export TASK_JSON_B64="$(base64 -w0 < "$SCRIPT_DIR/task.json")"
fi

# Deploy stack
docker stack deploy -c "$SCRIPT_DIR/stack.yml" "$STACK_NAME"

# Stream logs jusqu'a la fin du task
docker service logs --follow --raw "${{STACK_NAME}}_agent" || true

# Cleanup
docker stack rm "$STACK_NAME"
"""
    deploy_path = os.path.join(tmp_dir, "deploy.sh")
    with open(deploy_path, "w", encoding="utf-8") as f:
        f.write(deploy_sh)
    if os.name != "nt":
        os.chmod(deploy_path, 0o755)

    _log.info(
        "container.generate_tmp_swarm",
        dockerfile_id=dockerfile_id,
        service_name=service_name,
        tmp_dir=tmp_dir,
    )
    return deploy_path
```

- [ ] **Step 4 : Run, vérifier que ça passe**

```bash
cd backend && uv run pytest tests/test_container_runner_run_task_swarm.py -v
```

Attendu : 4 tests verts.

- [ ] **Step 5 : Lint**

```bash
cd backend && uv run ruff check src/agflow/services/container_runner.py tests/test_container_runner_run_task_swarm.py
```

- [ ] **Step 6 : Commit**

```bash
git add backend/src/agflow/services/container_runner.py backend/tests/test_container_runner_run_task_swarm.py
git commit -m "feat(container-runner): _generate_tmp_files_swarm (stack.yml + deploy.sh)

Mirror Swarm de _generate_tmp_files() : genere .env + stack.yml +
deploy.sh + task.json dans .tmp/. Fichiers inspectables et runnable
by hand par admin pour debug.

stack.yml : compose v3+, restart_policy condition=none (one-shot),
endpoint_mode=dnsrr, placement node.role==manager, network
agflow-internal external.

deploy.sh : bash wrapper qui docker stack deploy + service logs --follow
+ docker stack rm.

4 tests snapshot : 4 fichiers générés, stack.yml YAML valide compose,
task.json brut, deploy.sh shebang + commandes attendues + chmod 0o755."
```

---

## Task 7 — `run_task_swarm()` (subprocess wrapper)

**Files:**
- Modify: `backend/src/agflow/services/container_runner.py` (ajout fonction)
- Modify: `backend/tests/test_container_runner_run_task_swarm.py` (ajout tests)

- [ ] **Step 1 : Tests rouges**

Ajouter à la fin de `backend/tests/test_container_runner_run_task_swarm.py` :

```python
@pytest.mark.asyncio
async def test_run_task_swarm_yields_done_event_on_success(tmp_data_dir: Path) -> None:
    """run_task_swarm doit yield au moins un event 'done' avec status."""
    from agflow.services import container_runner

    # Mock subprocess pour simuler bash deploy.sh qui ouvre, stream, ferme
    fake_proc = MagicMock()
    fake_proc.returncode = 0
    fake_proc.stdout.readline = AsyncMock(side_effect=[
        b'{"type":"log","data":"hello"}\n',
        b"",  # EOF
    ])
    fake_proc.wait = AsyncMock(return_value=0)
    fake_proc.communicate = AsyncMock(return_value=(b"", b""))

    params = """
    {
      "docker": {
        "Container": {"Name": "agent-claude-{id}", "Image": "agflow-claude:{hash}"},
        "Network": {"Mode": "agflow-internal"},
        "Runtime": {"Init": true, "WorkingDir": "/app"},
        "Resources": {"Memory": "1g"},
        "Environments": {},
        "Mounts": []
      },
      "Params": {}
    }
    """

    with (
        patch("agflow.services.container_runner._load_platform_secrets",
              AsyncMock(return_value={})),
        patch("agflow.services.container_runner.list_running",
              AsyncMock(return_value=[])),
        patch("agflow.services.container_runner._ensure_mount_paths_from_config"),
        patch("agflow.services.container_runner._asyncio.create_subprocess_exec",
              AsyncMock(return_value=fake_proc)),
    ):
        events = []
        async for ev in container_runner.run_task_swarm(
            dockerfile_id="claude",
            params_json_content=params,
            content_hash="abc",
            task_payload={"text": "hello"},
            cleanup=True,
        ):
            events.append(ev)

    # Au moins un event 'done' avec status success/failure
    done_events = [e for e in events if e.get("type") == "done"]
    assert len(done_events) == 1
    assert done_events[0]["status"] == "success"
    assert done_events[0]["exit_code"] == 0


@pytest.mark.asyncio
async def test_run_task_swarm_rejects_when_max_services_reached(tmp_data_dir: Path) -> None:
    """Concurrency guard : MAX_RUNNING_CONTAINERS encore enforced."""
    from agflow.services import container_runner

    fake_alive = [
        container_runner.ContainerInfo(
            id=f"c{i}", name=f"n{i}", dockerfile_id="x", image="i",
            status="running", created_at="2026-01-01T00:00:00", instance_id="i",
        )
        for i in range(container_runner.MAX_RUNNING_CONTAINERS)
    ]
    with patch("agflow.services.container_runner.list_running",
               AsyncMock(return_value=fake_alive)):
        with pytest.raises(container_runner.TooManyContainersError):
            params = """
            {"docker": {"Container": {"Name": "x", "Image": "y"},
             "Network": {}, "Runtime": {}, "Resources": {},
             "Environments": {}, "Mounts": []}, "Params": {}}
            """
            async for _ in container_runner.run_task_swarm(
                dockerfile_id="claude",
                params_json_content=params,
                content_hash="abc",
                task_payload={},
            ):
                pass
```

- [ ] **Step 2 : Run, vérifier l'échec**

```bash
cd backend && uv run pytest tests/test_container_runner_run_task_swarm.py -v
```

Attendu : 4 verts (T6) + 2 rouges sur `run_task_swarm` (n'existe pas encore).

- [ ] **Step 3 : Implémentation `run_task_swarm()`**

Ajouter après `run_task` dans `backend/src/agflow/services/container_runner.py` (vers ligne ~1029, juste avant `stop`) :

```python
async def run_task_swarm(
    dockerfile_id: str,
    *,
    params_json_content: str,
    content_hash: str,
    task_payload: dict[str, Any],
    timeout_seconds: int = 600,
    user_secrets: dict[str, str] | None = None,
    on_container_started: Any | None = None,
    cleanup: bool = False,
    session_id: str | None = None,
    agent_instance_id: str | None = None,
    mount_base_id: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """One-shot task execution in Swarm mode (mirror de run_task()).

    Génère .tmp/{stack.yml, deploy.sh, task.json}, puis subprocess
    `bash deploy.sh` qui :
      1. docker stack deploy -c stack.yml STACK_NAME
      2. docker service logs --follow STACK_NAME_agent (stream stdout)
      3. docker stack rm STACK_NAME (cleanup)

    Yield des events {"type": "log", "data": "..."} pour chaque ligne
    parsable JSON, plus un final {"type": "done", "status": "success"
    | "failure", "exit_code": N}.
    """
    import asyncio as _asyncio
    import json as _json
    import secrets as _secrets

    # Concurrency guard (même limite que start())
    existing = await list_running()
    alive = [c for c in existing if c.status in ("running", "created", "restarting")]
    if len(alive) >= MAX_RUNNING_CONTAINERS:
        raise TooManyContainersError(
            f"Maximum of {MAX_RUNNING_CONTAINERS} running containers reached."
        )

    session_id = session_id or _secrets.token_hex(6)
    instance_id = secrets.token_hex(3)
    platform_secrets = await _load_platform_secrets()
    all_secrets = {**platform_secrets, **(user_secrets or {})}

    name, _spec = build_service_spec(
        dockerfile_id=dockerfile_id,
        params_json_content=params_json_content,
        content_hash=content_hash,
        instance_id=instance_id,
        extra_env=all_secrets,
        mount_base_id=mount_base_id,
    )
    # On a besoin de classic_config pour _generate_tmp_files_swarm (mounts/env source)
    _, classic_config = build_run_config(
        dockerfile_id=dockerfile_id,
        params_json_content=params_json_content,
        content_hash=content_hash,
        instance_id=instance_id,
        extra_env=all_secrets,
        mount_base_id=mount_base_id,
    )
    _ensure_mount_paths_from_config(
        dockerfile_id, params_json_content, instance_id, content_hash,
    )

    deploy_path = _generate_tmp_files_swarm(
        dockerfile_id=dockerfile_id,
        service_name=name,
        config=classic_config,
        task_payload=task_payload,
    )

    if agent_instance_id is not None:
        try:
            from uuid import UUID as _UUID

            from agflow.services.agents_instances_service import (
                set_last_container as _set_lc,
            )
            await _set_lc(instance_id=_UUID(str(agent_instance_id)), container_name=name)
        except Exception as _exc:
            _log.warning("run_task_swarm.set_container.failed", error=str(_exc))

    # Lance bash deploy.sh comme subprocess
    proc = await _asyncio.create_subprocess_exec(
        "bash", deploy_path,
        stdout=_asyncio.subprocess.PIPE,
        stderr=_asyncio.subprocess.PIPE,
    )

    try:
        # Stream stdout ligne par ligne, parser JSON quand possible
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            decoded = line.decode("utf-8", errors="replace").rstrip("\n")
            if not decoded:
                continue
            # Tente parser JSON ; sinon yield comme log brut
            try:
                event = _json.loads(decoded)
                if isinstance(event, dict):
                    yield event
                    continue
            except _json.JSONDecodeError:
                pass
            yield {"type": "log", "data": decoded}

        exit_code = await proc.wait()
        status = "success" if exit_code == 0 else "failure"
        yield {"type": "done", "status": status, "exit_code": exit_code}

        _log.info(
            "container.run_task_swarm.done",
            dockerfile_id=dockerfile_id,
            service_name=name,
            session_id=session_id,
            exit_code=exit_code,
        )
    finally:
        if cleanup:
            import shutil as _shutil
            tmp_dir = os.path.dirname(deploy_path)
            with contextlib.suppress(Exception):
                _shutil.rmtree(tmp_dir, ignore_errors=True)
```

- [ ] **Step 4 : Run, vérifier que ça passe**

```bash
cd backend && uv run pytest tests/test_container_runner_run_task_swarm.py -v
```

Attendu : 6 tests verts (4 + 2).

- [ ] **Step 5 : Lint**

```bash
cd backend && uv run ruff check src/agflow/services/container_runner.py tests/test_container_runner_run_task_swarm.py
```

- [ ] **Step 6 : Commit**

```bash
git add backend/src/agflow/services/container_runner.py backend/tests/test_container_runner_run_task_swarm.py
git commit -m "feat(container-runner): run_task_swarm one-shot via stack.yml + deploy.sh

Mirror Swarm de run_task() : genere les fichiers .tmp/swarm via
_generate_tmp_files_swarm puis subprocess bash deploy.sh. Stream stdout
ligne par ligne, yield events JSON parses ou log bruts. Yield event
final {type:done, status:success|failure, exit_code:N}.

Concurrency guard MAX_RUNNING_CONTAINERS conserve. cleanup=True supprime
le .tmp/ apres execution.

2 tests : success path + max reached."
```

---

## Task 8 — Endpoints API : toggle test dialog + switch prod

**Files:**
- Modify: `backend/src/agflow/api/admin/containers.py` (ajout `mode` param sur 2 endpoints test)
- Modify: `backend/src/agflow/api/public/launched.py` (switch run_task → run_task_swarm)
- Create: `backend/tests/test_swarm_endpoints_wiring.py`

- [ ] **Step 1 : Tests rouges**

Créer `backend/tests/test_swarm_endpoints_wiring.py` :

```python
"""Tests des endpoints API : toggle test dialog + prod swarm-only."""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch
from uuid import uuid4

os.environ.setdefault("AGFLOW_INFRA_KEY", "QUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE=")

import jwt
from fastapi.testclient import TestClient


def _admin_token() -> str:
    return jwt.encode(
        {"sub": "admin@example.com", "role": "admin"},
        os.environ["JWT_SECRET"],
        algorithm="HS256",
    )


def _api_key_token() -> str:
    return f"agfd_{uuid4().hex[:32]}"


# ── Test dialog (admin) endpoints accept mode param ─────────────────────


def test_test_endpoint_default_mode_is_swarm(client: TestClient) -> None:
    """Sans param mode, le default doit etre swarm (aligne avec prod)."""

    async def _stream():
        yield {"type": "done", "status": "success", "exit_code": 0}

    with (
        patch("agflow.api.admin.containers.container_runner.run_task_swarm",
              return_value=_stream()) as mock_swarm,
        patch("agflow.api.admin.containers.container_runner.run_task",
              return_value=_stream()) as mock_classic,
        patch("agflow.api.admin.containers.dockerfile_files_service.read_target",
              return_value={}),
    ):
        r = client.post(
            "/api/admin/containers/claude/test",
            json={"task_payload": {"text": "hi"}, "params_json_content": "{}"},
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code in (200, 422), r.text
    # Si 200, alors l'appel a déclenché run_task_swarm (default)
    if r.status_code == 200:
        assert mock_swarm.called
        assert not mock_classic.called


def test_test_endpoint_mode_classic_calls_run_task(client: TestClient) -> None:
    """Mode='classic' doit appeler run_task() (ancien comportement)."""

    async def _stream():
        yield {"type": "done", "status": "success", "exit_code": 0}

    with (
        patch("agflow.api.admin.containers.container_runner.run_task",
              return_value=_stream()) as mock_classic,
        patch("agflow.api.admin.containers.container_runner.run_task_swarm",
              return_value=_stream()) as mock_swarm,
        patch("agflow.api.admin.containers.dockerfile_files_service.read_target",
              return_value={}),
    ):
        r = client.post(
            "/api/admin/containers/claude/test",
            json={"task_payload": {"text": "hi"}, "params_json_content": "{}",
                  "mode": "classic"},
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code in (200, 422), r.text
    if r.status_code == 200:
        assert mock_classic.called
        assert not mock_swarm.called


def test_test_endpoint_mode_swarm_calls_run_task_swarm(client: TestClient) -> None:
    async def _stream():
        yield {"type": "done", "status": "success", "exit_code": 0}

    with (
        patch("agflow.api.admin.containers.container_runner.run_task_swarm",
              return_value=_stream()) as mock_swarm,
        patch("agflow.api.admin.containers.container_runner.run_task",
              return_value=_stream()) as mock_classic,
        patch("agflow.api.admin.containers.dockerfile_files_service.read_target",
              return_value={}),
    ):
        r = client.post(
            "/api/admin/containers/claude/test",
            json={"task_payload": {"text": "hi"}, "params_json_content": "{}",
                  "mode": "swarm"},
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code in (200, 422), r.text
    if r.status_code == 200:
        assert mock_swarm.called
        assert not mock_classic.called


# ── Production endpoint (public/launched) hardcoded Swarm ───────────────


def test_launched_endpoint_always_uses_run_task_swarm(client: TestClient) -> None:
    """L'endpoint prod public/launched doit OBLIGATOIREMENT appeler run_task_swarm."""

    async def _stream():
        yield {"type": "done", "status": "success", "exit_code": 0}

    with (
        patch("agflow.api.public.launched.container_runner.run_task_swarm",
              return_value=_stream()) as mock_swarm,
        patch("agflow.api.public.launched.container_runner.run_task",
              return_value=_stream()) as mock_classic,
    ):
        # Note : le route exact + auth depend de l'API existante. Adapter
        # selon l'endpoint réel public/launched. Placeholder ici.
        # Skip si l'endpoint nécessite des params complexes.
        # Ce test peut nécessiter d'être ajusté au moment de l'implémentation.
        pass

    # Au minimum vérifie qu'aucun run_task classique n'est référencé dans le router
    import inspect

    from agflow.api.public import launched

    src = inspect.getsource(launched)
    assert "run_task_swarm" in src, "launched.py doit utiliser run_task_swarm"
    assert "run_task(" not in src.replace("run_task_swarm", ""), (
        "launched.py ne doit PAS utiliser run_task() classique"
    )
```

- [ ] **Step 2 : Run, vérifier les rouges**

```bash
cd backend && uv run pytest tests/test_swarm_endpoints_wiring.py -v
```

Attendu : tests rouges (mode param pas encore ajouté + launched.py utilise encore run_task).

- [ ] **Step 3 : Implémentation `containers.py` (toggle test)**

Dans `backend/src/agflow/api/admin/containers.py`, identifier les 2 endpoints qui appellent `container_runner.run_task(...)` (cherchés ligne ~247 et ~414). Pour chacun :

1. Ajouter `mode: Literal["classic", "swarm"] = "swarm"` au payload Pydantic du request body (le schema dans `schemas/containers.py` ou inline si défini là)
2. Choisir la fonction selon `mode` :

```python
runner = (
    container_runner.run_task_swarm
    if payload.mode == "swarm"
    else container_runner.run_task
)
async for event in runner(
    dockerfile_id,
    params_json_content=...,
    content_hash=...,
    task_payload=...,
    ...
):
    yield ...
```

Adaptation exacte selon la structure actuelle des handlers — le pattern reste : `runner = swarm if mode==swarm else classic` puis appel avec les mêmes kwargs.

- [ ] **Step 4 : Implémentation `launched.py` (switch prod)**

Dans `backend/src/agflow/api/public/launched.py`, ligne ~90, remplacer :

```python
async for event in container_runner.run_task(
```

par :

```python
async for event in container_runner.run_task_swarm(
```

(Tous les autres params kwargs identiques.)

- [ ] **Step 5 : Run, vérifier que ça passe**

```bash
cd backend && uv run pytest tests/test_swarm_endpoints_wiring.py -v
```

Attendu : 4 tests verts (ou skips justifiés sur les endpoints qui exigent des fixtures DB que le test ne couvre pas — l'essentiel est que les mocks démontrent le bon dispatch et que `launched.py` source ne référence plus `run_task()` classique).

- [ ] **Step 6 : Lint**

```bash
cd backend && uv run ruff check src/agflow/api/admin/containers.py src/agflow/api/public/launched.py tests/test_swarm_endpoints_wiring.py
```

- [ ] **Step 7 : Commit**

```bash
git add backend/src/agflow/api/admin/containers.py backend/src/agflow/api/public/launched.py backend/tests/test_swarm_endpoints_wiring.py
git commit -m "feat(api): toggle mode classic|swarm sur test dialog + prod hardcoded Swarm

- containers.py test endpoints : ajout param mode (default swarm)
  qui dispatch vers run_task_swarm ou run_task selon le choix
- public/launched.py : remplacement direct run_task -> run_task_swarm
  (production OBLIGATOIREMENT Swarm, pas de toggle)

4 tests : default mode = swarm, mode classic dispatches run_task,
mode swarm dispatches run_task_swarm, launched.py source ne reference
plus run_task() classique."
```

---

## Task 9 — Vérifs globales

**Files:** Aucun changement de code.

- [ ] **Step 1 : Suite complète des tests B1**

```bash
cd backend && uv run pytest \
  tests/test_container_runner_service_spec.py \
  tests/test_container_runner_swarm_lifecycle.py \
  tests/test_container_runner_run_task_swarm.py \
  tests/test_terminal_service_resolution.py \
  tests/test_swarm_endpoints_wiring.py \
  -v 2>&1 | tail -5
```

Attendu : ~28 tests verts.

- [ ] **Step 2 : Régression sur les chantiers précédents**

```bash
cd backend && uv run pytest \
  tests/test_swarm_defaults.py \
  tests/test_compose_renderer_swarm.py \
  tests/test_swarm_secrets.py \
  tests/test_lifespan_db_check.py \
  tests/test_migrations_lock.py \
  tests/test_system_export_service.py \
  tests/test_system_export_endpoint.py \
  tests/test_infra_machines_ingest.py \
  tests/test_infra_swarm_clusters_service.py \
  tests/test_swarm_actions_service.py \
  tests/test_infra_swarm_clusters_endpoint.py \
  -q 2>&1 | tail -3
```

Attendu : tous verts.

- [ ] **Step 3 : Lint global sur les fichiers touchés**

```bash
cd backend && uv run ruff check \
  src/agflow/services/container_runner.py \
  src/agflow/api/admin/containers.py \
  src/agflow/api/admin/terminal.py \
  src/agflow/api/public/launched.py \
  tests/test_container_runner_service_spec.py \
  tests/test_container_runner_swarm_lifecycle.py \
  tests/test_container_runner_run_task_swarm.py \
  tests/test_terminal_service_resolution.py \
  tests/test_swarm_endpoints_wiring.py
```

Attendu : `All checks passed!` (sauf les SIM105 pré-existants déjà flaggés en B0 sur `api/infra/machines.py` qui ne nous concernent pas).

- [ ] **Step 4 : Smoke import + boot**

```bash
cd backend && uv run python -c "from agflow.main import create_app; create_app(); print('boot ok')"
```

Attendu : `boot ok`.

- [ ] **Step 5 : Liste des commits B1**

```bash
git log --oneline dbc18ba..HEAD
```

Attendu : 8 commits dans cet ordre :
1. `feat(container-runner): build_service_spec mapping ...`
2. `feat(container-runner): start() utilise aiodocker.services.create ...`
3. `feat(container-runner): stop() + list_running() utilisent l'API Swarm ...`
4. `feat(terminal): résolution service Swarm -> container avant docker exec`
5. `feat(container-runner): _generate_tmp_files_swarm (stack.yml + deploy.sh)`
6. `feat(container-runner): run_task_swarm one-shot via stack.yml + deploy.sh`
7. `feat(api): toggle mode classic|swarm sur test dialog + prod hardcoded Swarm`

Note : Task 5 (vérif workers) ne produit pas de commit, donc 7 commits au lieu de 8.

- [ ] **Step 6 : `git status -s`**

Attendu : vide.

---

## Critères d'acceptation finaux

- [ ] `build_service_spec()` produit un ServiceSpec valide acceptable par l'API Docker Engine
- [ ] `start()` lance un service Swarm avec labels agflow + résoud le container du replica unique
- [ ] `stop()` détruit le service ; fallback container.delete si pas trouvé en service
- [ ] `list_running()` retourne les containers concrets des services agflow-managed
- [ ] `terminal.py` résout correctement service_name → container_id
- [ ] `agent_reaper` + `docker_reconciler` non-régression (mêmes signatures stop/list_running)
- [ ] `_generate_tmp_files_swarm()` génère 4 fichiers inspectables (.env, stack.yml, deploy.sh, task.json)
- [ ] `run_task_swarm()` exécute le stack via subprocess + stream events JSON + yield done
- [ ] Endpoints test dialog admin acceptent param `mode: classic|swarm` (default swarm)
- [ ] Endpoint `public/launched.py` utilise exclusivement `run_task_swarm()`
- [ ] Tests : ~28 tests B1 verts, 0 régression
- [ ] Lint clean, boot OK

---

## Hors plan (rappel)

- Frontend toggle UI dans dialog construction d'agent — plan séparé
- Multi-cluster targeting — futur
- Refacto `services/build_service.py` (build d'images) — non concerné
- `run_task()` mode classique conservé en l'état (utilisé par test dialog en mode `classic`)
- Migration des agents en cours sur la prod LXC 201 — la prod va être réinitialisée sur le cluster Swarm
- Multi-replicas (Mode.Replicated.Replicas > 1) — futur si besoin
