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
        side_effect=_aio.exceptions.DockerError(404, {"message": "not a service"}),
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

    with (
        patch("agflow.api.admin.terminal.aiodocker.Docker", return_value=docker),
        pytest.raises(ValueError, match="no running task"),
    ):
        await _resolve_to_container_id("agent-x")
