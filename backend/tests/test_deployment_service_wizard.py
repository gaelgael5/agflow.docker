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
