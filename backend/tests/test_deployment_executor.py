import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from datetime import datetime


def _make_deployment(status="generated", step_index=0, accumulated_env=None):
    from agflow.schemas.products import DeploymentSummary, StepLog
    return DeploymentSummary(
        id=uuid4(), project_id=uuid4(), user_id=uuid4(),
        status=status, current_step_index=step_index,
        accumulated_env=accumulated_env or {},
        step_logs=[], group_servers={"grp1": "mach1"},
        generated_env="VAR=val", generated_secrets={},
        nullable_secrets=[], generated_data={},
        created_at=datetime.now(), updated_at=datetime.now(),
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

    with patch("agflow.services.deployment_executor.project_deployments_service") as mock_svc, \
         patch("agflow.services.deployment_executor.scripts_service") as mock_scripts, \
         patch("agflow.services.deployment_executor._run_script_streaming", new_callable=AsyncMock) as mock_run, \
         patch("agflow.services.deployment_executor.log_bus") as mock_bus:

        mock_svc.get_by_id = AsyncMock(return_value=dep)
        mock_svc.get_ordered_before_scripts = AsyncMock(return_value=[link])
        mock_svc.set_status = AsyncMock()
        mock_svc.advance_step = AsyncMock(return_value=dep)

        mock_scripts.get_by_id = AsyncMock(return_value=MagicMock(content="echo '{}'"))
        mock_scripts.ScriptNotFoundError = Exception

        mock_run.return_value = {
            "success": True, "exit_code": 0,
            "stdout": '{"KC_ID": "abc"}', "stderr": "",
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
    """Quand le script échoue, on passe à step_failed."""
    dep = _make_deployment()
    link = _make_link()

    with patch("agflow.services.deployment_executor.project_deployments_service") as mock_svc, \
         patch("agflow.services.deployment_executor.scripts_service") as mock_scripts, \
         patch("agflow.services.deployment_executor._run_script_streaming", new_callable=AsyncMock) as mock_run, \
         patch("agflow.services.deployment_executor.log_bus") as mock_bus, \
         patch("agflow.services.deployment_executor.db_execute", new_callable=AsyncMock):

        mock_svc.get_by_id = AsyncMock(return_value=dep)
        mock_svc.get_ordered_before_scripts = AsyncMock(return_value=[link])
        mock_svc.set_status = AsyncMock()
        mock_scripts.get_by_id = AsyncMock(return_value=MagicMock(content="exit 1"))
        mock_scripts.ScriptNotFoundError = Exception

        mock_run.return_value = {"success": False, "exit_code": 1, "stdout": "", "stderr": "error"}
        mock_bus.publish = AsyncMock()
        mock_bus.close = AsyncMock()

        from agflow.services.deployment_executor import execute_step
        await execute_step(dep.id)

        mock_svc.set_status.assert_any_await(dep.id, "step_failed")


@pytest.mark.asyncio
async def test_execute_step_no_scripts_transitions_to_before_complete():
    """Quand il n'y a pas de before-scripts, on passe directement à before_complete."""
    dep = _make_deployment()

    with patch("agflow.services.deployment_executor.project_deployments_service") as mock_svc, \
         patch("agflow.services.deployment_executor.log_bus") as mock_bus:

        mock_svc.get_by_id = AsyncMock(return_value=dep)
        mock_svc.get_ordered_before_scripts = AsyncMock(return_value=[])
        mock_svc.set_status = AsyncMock()
        mock_bus.publish = AsyncMock()
        mock_bus.close = AsyncMock()

        from agflow.services.deployment_executor import execute_step
        await execute_step(dep.id)

        mock_svc.set_status.assert_awaited_once_with(dep.id, "before_complete")
