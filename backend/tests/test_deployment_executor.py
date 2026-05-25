from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest


def _make_deployment(status="generated", step_index=0, accumulated_env=None):
    from agflow.schemas.products import DeploymentSummary

    return DeploymentSummary(
        id=uuid4(),
        project_id=uuid4(),
        user_id=uuid4(),
        status=status,
        current_step_index=step_index,
        accumulated_env=accumulated_env or {},
        step_logs=[],
        group_servers={"grp1": "mach1"},
        generated_env="VAR=val",
        generated_secrets={},
        nullable_secrets=[],
        generated_data={},
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


def _make_link(position=0, timing="before"):
    link = MagicMock()
    link.id = uuid4()
    link.script_id = uuid4()
    link.timing = timing
    link.position = position
    link.input_values = {}
    link.trigger_rules = []
    link.script_name = "test-script"
    link.machine_name = "test-machine"
    link.env_mapping = {}
    link.group_name = "group1"
    return link


@pytest.mark.asyncio
async def test_execute_step_success_transitions_to_before_complete():
    """Quand il n'y a qu'un step et qu'il réussit, on passe à before_complete."""
    dep = _make_deployment()
    link = _make_link()

    with (
        patch("agflow.services.deployment_executor.project_deployments_service") as mock_svc,
        patch("agflow.services.deployment_executor.scripts_service") as mock_scripts,
        patch(
            "agflow.services.deployment_executor._run_script_streaming", new_callable=AsyncMock
        ) as mock_run,
        patch("agflow.services.deployment_executor.log_bus") as mock_bus,
    ):
        mock_svc.get_by_id = AsyncMock(return_value=dep)
        mock_svc.get_ordered_before_scripts = AsyncMock(return_value=[link])
        mock_svc.set_status = AsyncMock()
        mock_svc.advance_step = AsyncMock(return_value=dep)

        mock_scripts.get_by_id = AsyncMock(return_value=MagicMock(content="echo '{}'"))
        mock_scripts.ScriptNotFoundError = Exception

        mock_run.return_value = {
            "success": True,
            "exit_code": 0,
            "stdout": '{"KC_ID": "abc"}',
            "stderr": "",
        }
        mock_bus.publish = AsyncMock()
        mock_bus.close = AsyncMock()

        from agflow.services.deployment_executor import execute_step

        await execute_step(dep.id)

        mock_svc.advance_step.assert_awaited_once()
        call_kwargs = mock_svc.advance_step.call_args.kwargs
        assert call_kwargs["next_status"] == "before_complete"


@pytest.mark.asyncio
async def test_execute_step_failure_sets_step_failed():
    """Quand le script échoue, fail_step est appelé de manière atomique."""
    dep = _make_deployment()
    link = _make_link()

    with (
        patch("agflow.services.deployment_executor.project_deployments_service") as mock_svc,
        patch("agflow.services.deployment_executor.scripts_service") as mock_scripts,
        patch(
            "agflow.services.deployment_executor._run_script_streaming", new_callable=AsyncMock
        ) as mock_run,
        patch("agflow.services.deployment_executor.log_bus") as mock_bus,
    ):
        mock_svc.get_by_id = AsyncMock(return_value=dep)
        mock_svc.get_ordered_before_scripts = AsyncMock(return_value=[link])
        mock_svc.fail_step = AsyncMock()
        mock_scripts.get_by_id = AsyncMock(return_value=MagicMock(content="exit 1"))
        mock_scripts.ScriptNotFoundError = Exception

        mock_run.return_value = {"success": False, "exit_code": 1, "stdout": "", "stderr": "error"}
        mock_bus.publish = AsyncMock()
        mock_bus.close = AsyncMock()

        from agflow.services.deployment_executor import execute_step

        await execute_step(dep.id)

        mock_svc.fail_step.assert_awaited_once()
        call_args = mock_svc.fail_step.call_args
        assert call_args.args[0] == dep.id
        step_log = call_args.args[1]
        assert step_log["exit_code"] == 1
        mock_bus.close.assert_awaited_once_with(dep.id)


@pytest.mark.asyncio
async def test_execute_step_script_not_found():
    """Quand ScriptNotFoundError est levée, fail_step est appelé et le bus est fermé."""
    dep = _make_deployment()
    link = _make_link()

    class ScriptNotFoundError(Exception):
        pass

    with (
        patch("agflow.services.deployment_executor.project_deployments_service") as mock_svc,
        patch("agflow.services.deployment_executor.scripts_service") as mock_scripts,
        patch("agflow.services.deployment_executor.log_bus") as mock_bus,
    ):
        mock_svc.get_by_id = AsyncMock(return_value=dep)
        mock_svc.get_ordered_before_scripts = AsyncMock(return_value=[link])
        mock_svc.fail_step = AsyncMock()
        mock_scripts.get_by_id = AsyncMock(side_effect=ScriptNotFoundError("not found"))
        mock_scripts.ScriptNotFoundError = ScriptNotFoundError
        mock_bus.publish = AsyncMock()
        mock_bus.close = AsyncMock()

        from agflow.services.deployment_executor import execute_step

        await execute_step(dep.id)

        mock_svc.fail_step.assert_awaited_once()
        call_args = mock_svc.fail_step.call_args
        assert call_args.args[0] == dep.id
        step_log = call_args.args[1]
        assert step_log["exit_code"] == -1
        mock_bus.close.assert_awaited_once_with(dep.id)


@pytest.mark.asyncio
async def test_execute_step_step_complete_when_not_last():
    """Quand il y a 2 scripts et step_index=0, le succès → step_complete (pas before_complete)."""
    dep = _make_deployment(step_index=0)
    link0 = _make_link(position=0)
    link1 = _make_link(position=1)

    with (
        patch("agflow.services.deployment_executor.project_deployments_service") as mock_svc,
        patch("agflow.services.deployment_executor.scripts_service") as mock_scripts,
        patch(
            "agflow.services.deployment_executor._run_script_streaming", new_callable=AsyncMock
        ) as mock_run,
        patch("agflow.services.deployment_executor.log_bus") as mock_bus,
    ):
        mock_svc.get_by_id = AsyncMock(return_value=dep)
        mock_svc.get_ordered_before_scripts = AsyncMock(return_value=[link0, link1])
        mock_svc.advance_step = AsyncMock(return_value=dep)
        mock_scripts.get_by_id = AsyncMock(return_value=MagicMock(content="echo '{}'"))
        mock_scripts.ScriptNotFoundError = Exception

        mock_run.return_value = {
            "success": True,
            "exit_code": 0,
            "stdout": "{}",
            "stderr": "",
        }
        mock_bus.publish = AsyncMock()
        mock_bus.close = AsyncMock()

        from agflow.services.deployment_executor import execute_step

        await execute_step(dep.id)

        mock_svc.advance_step.assert_awaited_once()
        call_kwargs = mock_svc.advance_step.call_args.kwargs
        assert call_kwargs["next_status"] == "step_complete"
        mock_bus.close.assert_awaited_once_with(dep.id)


@pytest.mark.asyncio
async def test_execute_step_trigger_skip():
    """Quand evaluate_trigger_rules retourne False, advance_step est appelé avec le bon next_status."""
    dep = _make_deployment(step_index=0)
    link = _make_link(position=0)
    link.trigger_rules = [{"variable": "SKIP_FLAG", "op": "equals", "value": "yes"}]

    with (
        patch("agflow.services.deployment_executor.project_deployments_service") as mock_svc,
        patch("agflow.services.deployment_executor.scripts_service") as mock_scripts,
        patch("agflow.services.deployment_executor.log_bus") as mock_bus,
    ):
        mock_svc.get_by_id = AsyncMock(return_value=dep)
        mock_svc.get_ordered_before_scripts = AsyncMock(return_value=[link])
        mock_svc.advance_step = AsyncMock(return_value=dep)
        mock_scripts.get_by_id = AsyncMock(return_value=MagicMock(content="echo hello"))
        mock_scripts.ScriptNotFoundError = Exception
        mock_bus.publish = AsyncMock()
        mock_bus.close = AsyncMock()

        from agflow.services.deployment_executor import execute_step

        await execute_step(dep.id)

        # SKIP_FLAG n'est pas dans le .env (VAR=val), donc la règle échoue → skip
        mock_svc.advance_step.assert_awaited_once()
        call_kwargs = mock_svc.advance_step.call_args.kwargs
        # Seul 1 script → step_index + 1 == len(before_scripts) → before_complete
        assert call_kwargs["next_status"] == "before_complete"
        mock_bus.close.assert_awaited_once_with(dep.id)


@pytest.mark.asyncio
async def test_execute_step_no_scripts_transitions_to_before_complete():
    """Quand il n'y a pas de before-scripts, on passe directement à before_complete."""
    dep = _make_deployment()

    with (
        patch("agflow.services.deployment_executor.project_deployments_service") as mock_svc,
        patch("agflow.services.deployment_executor.log_bus") as mock_bus,
    ):
        mock_svc.get_by_id = AsyncMock(return_value=dep)
        mock_svc.get_ordered_before_scripts = AsyncMock(return_value=[])
        mock_svc.set_status = AsyncMock()
        mock_bus.publish = AsyncMock()
        mock_bus.close = AsyncMock()

        from agflow.services.deployment_executor import execute_step

        await execute_step(dep.id)

        mock_svc.set_status.assert_awaited_once_with(dep.id, "before_complete")


@pytest.mark.asyncio
async def test_run_script_streaming_fails_on_unresolved_placeholder() -> None:
    """Si input_resolver lève, le streaming échoue AVANT l'upload SSH."""
    from types import SimpleNamespace

    from agflow.services import deployment_executor
    from agflow.services.input_resolver import UnresolvedPlaceholderError

    link = SimpleNamespace(
        id=uuid4(),
        input_values={"PWD": "${env-machine://ghost:VAR}"},
        script_name="dummy",
        machine_name="target",
        timing="before",
    )

    captured_lines: list[tuple[str, str]] = []

    async def on_line(stream: str, line: str) -> None:
        captured_lines.append((stream, line))

    with (
        patch(
            "agflow.services.deployment_executor.group_scripts_service.resolve_target_machine_id",
            new_callable=AsyncMock,
            return_value=uuid4(),
        ),
        patch(
            "agflow.services.deployment_executor.ssh_kwargs_for_machine",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch(
            "agflow.services.deployment_executor.platform_secrets_service.resolve_all",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch(
            "agflow.services.deployment_executor.input_resolver.resolve_input_values",
            new_callable=AsyncMock,
            side_effect=UnresolvedPlaceholderError(
                kind="machine_not_found",
                ref="${env-machine://ghost:VAR}",
                detail="machine 'ghost' inconnue",
                var_name="PWD",
            ),
        ),
        patch(
            "agflow.services.deployment_executor.ssh_executor.exec_command",
            new_callable=AsyncMock,
        ) as mock_exec,
    ):
        result = await deployment_executor._run_script_streaming(
            link=link,
            script_content="echo {PWD}",
            env_text="",
            on_line=on_line,
        )

    assert result["success"] is False
    assert result["exit_code"] == -1
    assert "PWD" in result["stderr"]
    assert "ghost" in result["stderr"]
    # Aucun exec_command appelé : on a fail avant l'upload
    mock_exec.assert_not_called()
    # Le stderr a été propagé via on_line
    assert any(s == "stderr" and "ghost" in line for s, line in captured_lines)
