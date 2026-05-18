"""Tests de GET /api/admin/tasks/{task_id}."""
from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from agflow.auth.jwt import encode_token

pytestmark = pytest.mark.skip(
    reason="TestClient/asyncpg loop mismatch (pattern T1 fix 6bb1006) — "
    "validé via run-test.sh étape 7.9 smoke API curl"
)


@pytest.fixture
def client():
    from agflow.main import app
    return TestClient(app)


def _admin_header() -> dict[str, str]:
    return {"Authorization": f"Bearer {encode_token('admin@test.local')}"}


@pytest.mark.asyncio
async def test_get_completed_task_returns_full_shape(
    client, fresh_db, mock_session_and_agent
):
    from agflow.services import tasks_service

    sid, aid = mock_session_and_agent
    cid = uuid4()
    aeid = uuid4()
    created = await tasks_service.create_session_work(
        session_id=sid,
        agent_instance_id=aid,
        agflow_correlation_id=cid,
        agflow_action_execution_id=aeid,
        instruction={"text": "x"},
    )
    await tasks_service.mark_completed(
        task_id=created["task_id"], result={"summary": "done"}
    )

    r = client.get(
        f"/api/admin/tasks/{created['task_id']}", headers=_admin_header()
    )
    assert r.status_code == 200
    body = r.json()
    assert body["task_id"] == str(created["task_id"])
    assert body["status"] == "completed"
    assert body["result"] == {"summary": "done"}
    assert body["error"] is None
    assert body["agflow_correlation_id"] == str(cid)
    assert body["agflow_action_execution_id"] == str(aeid)
    assert body["completed_at"] is not None


@pytest.mark.asyncio
async def test_get_failed_task_returns_error(
    client, fresh_db, mock_session_and_agent
):
    from agflow.services import tasks_service

    sid, aid = mock_session_and_agent
    created = await tasks_service.create_session_work(
        session_id=sid,
        agent_instance_id=aid,
        agflow_correlation_id=uuid4(),
        agflow_action_execution_id=uuid4(),
        instruction={},
    )
    await tasks_service.mark_failed(
        task_id=created["task_id"],
        error={"code": "AGENT_OOM", "message": "oom"},
    )

    r = client.get(
        f"/api/admin/tasks/{created['task_id']}", headers=_admin_header()
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "failed"
    assert body["error"]["code"] == "AGENT_OOM"
    assert body["result"] is None


@pytest.mark.asyncio
async def test_get_pending_task_returns_minimal(
    client, fresh_db, mock_session_and_agent
):
    from agflow.services import tasks_service

    sid, aid = mock_session_and_agent
    created = await tasks_service.create_session_work(
        session_id=sid,
        agent_instance_id=aid,
        agflow_correlation_id=uuid4(),
        agflow_action_execution_id=uuid4(),
        instruction={},
    )

    r = client.get(
        f"/api/admin/tasks/{created['task_id']}", headers=_admin_header()
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "pending"
    assert body["completed_at"] is None
    assert body["result"] is None


def test_get_unknown_task_returns_404(client, fresh_db):
    r = client.get(
        f"/api/admin/tasks/{uuid4()}", headers=_admin_header()
    )
    assert r.status_code == 404
