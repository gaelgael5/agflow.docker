"""Tests pour swarm_actions_service avec mocks ssh_executor + DB layer."""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

# Fix la cle Fernet pour la reproductibilite (32 bytes url-safe base64)
os.environ["AGFLOW_INFRA_KEY"] = "QUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUFBQUE="

from agflow.services.swarm_actions_service import (
    SwarmActionError,
    init_cluster,
    join_cluster,
    leave_cluster,
)

_INIT_SCRIPT_OUTPUT = {
    "status": "ok",
    "exit_code": 0,
    "swarm": {
        "cluster_name": "swarm1",
        "manager_addr": "192.168.10.300:2377",
        "join_token_worker": "SWMTKN-1-worker-abc",
        "join_token_manager": "SWMTKN-1-manager-xyz",
    },
}


@pytest.mark.asyncio
async def test_init_cluster_runs_script_and_persists() -> None:
    machine_id = uuid4()

    with (
        patch(
            "agflow.services.swarm_actions_service._get_machine",
            AsyncMock(return_value={
                "id": machine_id, "host": "192.168.10.300", "port": 22,
                "username": "agflow", "swarm_ready": True, "swarm_cluster_id": None,
                "certificate_id": None,
            }),
        ),
        patch(
            "agflow.services.swarm_actions_service._exec_swarm_script",
            AsyncMock(return_value=_INIT_SCRIPT_OUTPUT),
        ) as mock_exec,
        patch(
            "agflow.services.swarm_actions_service._persist_init_result",
            AsyncMock(return_value={"id": uuid4(), "name": "swarm1"}),
        ) as mock_persist,
    ):
        result = await init_cluster(machine_id=machine_id, cluster_name="swarm1")

    assert mock_exec.called
    assert mock_persist.called
    assert result["name"] == "swarm1"


@pytest.mark.asyncio
async def test_init_cluster_rejects_machine_already_in_cluster() -> None:
    machine_id = uuid4()

    with (
        patch(
            "agflow.services.swarm_actions_service._get_machine",
            AsyncMock(return_value={
                "id": machine_id, "swarm_cluster_id": uuid4(),  # already member
            }),
        ),
        pytest.raises(SwarmActionError, match="already member"),
    ):
        await init_cluster(machine_id=machine_id, cluster_name="swarm2")


@pytest.mark.asyncio
async def test_init_cluster_rejects_machine_not_swarm_ready() -> None:
    machine_id = uuid4()

    with (
        patch(
            "agflow.services.swarm_actions_service._get_machine",
            AsyncMock(return_value={
                "id": machine_id, "swarm_ready": False, "swarm_cluster_id": None,
            }),
        ),
        pytest.raises(SwarmActionError, match="not swarm-ready"),
    ):
        await init_cluster(machine_id=machine_id, cluster_name="swarm1")


@pytest.mark.asyncio
async def test_init_cluster_rejects_when_script_returns_partial() -> None:
    machine_id = uuid4()

    with (
        patch(
            "agflow.services.swarm_actions_service._get_machine",
            AsyncMock(return_value={
                "id": machine_id, "swarm_ready": True, "swarm_cluster_id": None,
            }),
        ),
        patch(
            "agflow.services.swarm_actions_service._exec_swarm_script",
            AsyncMock(return_value={"status": "partial", "exit_code": 2}),
        ),
        pytest.raises(SwarmActionError, match="partial"),
    ):
        await init_cluster(machine_id=machine_id, cluster_name="swarm1")


@pytest.mark.asyncio
async def test_join_cluster_succeeds_with_worker_role() -> None:
    machine_id = uuid4()
    cluster_id = uuid4()

    with (
        patch("agflow.services.swarm_actions_service._get_machine", AsyncMock(return_value={
            "id": machine_id, "host": "192.168.10.301", "port": 22,
            "username": "agflow", "swarm_ready": True, "swarm_cluster_id": None,
            "certificate_id": None,
        })),
        patch(
            "agflow.services.infra_swarm_clusters_service.get_with_tokens",
            AsyncMock(return_value={
                "id": cluster_id, "name": "swarm1", "manager_addr": "10.0.0.1:2377",
                "join_token_worker_encrypted": "ENC1",
                "join_token_manager_encrypted": "ENC2",
            }),
        ),
        patch(
            "agflow.services.infra_swarm_clusters_service.decrypt_tokens",
            return_value={"worker": "WT-clear", "manager": "MT-clear"},
        ),
        patch("agflow.services.swarm_actions_service._exec_swarm_script",
              AsyncMock(return_value={"status": "ok", "exit_code": 0,
                                       "swarm": {"joined": True, "node_id": "n1", "role": "worker"}})),
        patch("agflow.services.swarm_actions_service.execute", AsyncMock()),
    ):
        result = await join_cluster(machine_id=machine_id, cluster_id=cluster_id, role="worker")

    assert result["joined"] is True
    assert result["role"] == "worker"


@pytest.mark.asyncio
async def test_join_cluster_rejects_unknown_cluster() -> None:
    machine_id = uuid4()

    with (
        patch("agflow.services.swarm_actions_service._get_machine", AsyncMock(return_value={
            "id": machine_id, "swarm_ready": True, "swarm_cluster_id": None,
        })),
        patch(
            "agflow.services.infra_swarm_clusters_service.get_with_tokens",
            AsyncMock(return_value=None),
        ),
        pytest.raises(SwarmActionError, match=r"Cluster .* not found"),
    ):
        await join_cluster(machine_id=machine_id, cluster_id=uuid4(), role="worker")


@pytest.mark.asyncio
async def test_leave_cluster_drops_cluster_when_last_node() -> None:
    machine_id = uuid4()
    cluster_id = uuid4()

    with (
        patch("agflow.services.swarm_actions_service._get_machine", AsyncMock(return_value={
            "id": machine_id, "host": "10.0.0.2", "port": 22, "username": "agflow",
            "swarm_cluster_id": cluster_id, "swarm_node_role": "manager",
            "certificate_id": None,
        })),
        patch("agflow.services.swarm_actions_service._exec_swarm_script",
              AsyncMock(return_value={"status": "ok", "exit_code": 0, "swarm": {"left": True}})),
        patch("agflow.services.swarm_actions_service.execute", AsyncMock()),
        patch("agflow.services.infra_swarm_clusters_service.is_last_node",
              AsyncMock(return_value=True)),
        patch("agflow.services.infra_swarm_clusters_service.delete",
              AsyncMock()) as mock_delete,
    ):
        result = await leave_cluster(machine_id=machine_id)

    assert result["left"] is True
    assert result["cluster_dropped"] is True
    mock_delete.assert_called_once_with(cluster_id)


@pytest.mark.asyncio
async def test_leave_cluster_keeps_cluster_when_other_nodes_remain() -> None:
    machine_id = uuid4()
    cluster_id = uuid4()

    with (
        patch("agflow.services.swarm_actions_service._get_machine", AsyncMock(return_value={
            "id": machine_id, "host": "10.0.0.3", "port": 22, "username": "agflow",
            "swarm_cluster_id": cluster_id, "swarm_node_role": "worker",
            "certificate_id": None,
        })),
        patch("agflow.services.swarm_actions_service._exec_swarm_script",
              AsyncMock(return_value={"status": "ok", "exit_code": 0, "swarm": {"left": True}})),
        patch("agflow.services.swarm_actions_service.execute", AsyncMock()),
        patch("agflow.services.infra_swarm_clusters_service.is_last_node",
              AsyncMock(return_value=False)),
        patch("agflow.services.infra_swarm_clusters_service.delete",
              AsyncMock()) as mock_delete,
    ):
        result = await leave_cluster(machine_id=machine_id)

    assert result["left"] is True
    assert result["cluster_dropped"] is False
    mock_delete.assert_not_called()
