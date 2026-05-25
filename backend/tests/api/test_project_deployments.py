# backend/tests/api/test_project_deployments.py
"""Tests unitaires pour agflow.api.admin.project_deployments (mocks complets)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_run_group_script_fails_on_unresolved_placeholder() -> None:
    """_run_group_script échoue proprement si input_resolver lève."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch
    from uuid import uuid4

    from agflow.api.admin import project_deployments
    from agflow.services.input_resolver import UnresolvedPlaceholderError

    link = SimpleNamespace(
        id=uuid4(),
        input_values={"X": "${env-machine://ghost:Y}"},
        script_name="dummy",
        machine_name="target",
        timing="before",
        position=0,
    )

    with (
        patch(
            "agflow.api.admin.project_deployments.group_scripts_service.resolve_target_machine_id",
            new_callable=AsyncMock,
            return_value=uuid4(),
        ),
        patch(
            "agflow.api.admin.project_deployments._ssh_kwargs_for_machine",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch(
            "agflow.api.admin.project_deployments.platform_secrets_service.resolve_all",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch(
            "agflow.api.admin.project_deployments.input_resolver.resolve_input_values",
            new_callable=AsyncMock,
            side_effect=UnresolvedPlaceholderError(
                kind="machine_not_found",
                ref="${env-machine://ghost:Y}",
                detail="machine 'ghost' inconnue",
                var_name="X",
            ),
        ),
        patch(
            "agflow.api.admin.project_deployments.ssh_executor.exec_command",
            new_callable=AsyncMock,
        ) as mock_exec,
    ):
        result = await project_deployments._run_group_script(link, "echo {X}", env_text="")

    assert result["success"] is False
    assert "X" in result["error"]
    assert "ghost" in result["error"]
    mock_exec.assert_not_called()
