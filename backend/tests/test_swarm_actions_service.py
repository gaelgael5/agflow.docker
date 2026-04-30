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
