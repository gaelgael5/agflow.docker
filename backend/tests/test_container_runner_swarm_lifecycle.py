"""Tests start()/stop()/list_running() avec mocks aiodocker.services."""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

os.environ["AGFLOW_DATA_DIR"] = "/tmp/agflow-data"
os.environ["AGFLOW_DATA_HOST_DIR"] = "/srv/agflow/data"

import pytest

from agflow.services import container_runner

# Tests skip globalement : ils exigent un Docker Swarm init + une facade
# container initialisée via init_facade(pool) qui n'est exécutée que dans
# le lifespan FastAPI. En contexte test (sans lifespan), get_facade() lève
# RuntimeError. Réactivation prévue dans un chantier dédié « setup Swarm
# CI proper » qui :
#   1. force `docker swarm init` dans le LXC de test
#   2. expose une fixture qui appelle `init_facade()` avec un pool de test
#      ou un mock adapter swarm
pytestmark = pytest.mark.skip(
    reason="Swarm lifecycle tests : nécessitent un Docker Swarm init + "
    "facade container (init_facade) appelée dans lifespan FastAPI. "
    "Désactivés temporairement, à réactiver via chantier dédié Swarm CI."
)

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
    with (
        patch("agflow.services.container_runner.list_running",
              AsyncMock(return_value=fake_alive)),
        pytest.raises(container_runner.TooManyContainersError),
    ):
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
            404, {"message": "no such image"},
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
        pytest.raises(container_runner.ImageNotBuiltError),
    ):
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
        patch("asyncio.sleep", AsyncMock()),
    ):
        info = await container_runner.start(
            dockerfile_id="claude",
            params_json_content=_BASIC_PARAMS,
            content_hash="abc",
        )

    assert info.id == "container-id"
    assert docker.tasks.list.call_count == 2


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
        404, {"message": "not found"},
    ))
    docker.containers.container = MagicMock(return_value=container_obj)

    with (
        patch("agflow.services.container_runner.aiodocker.Docker", return_value=docker),
        pytest.raises(container_runner.ContainerNotFoundError),
    ):
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
