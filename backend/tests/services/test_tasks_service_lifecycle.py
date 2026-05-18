"""Tests du cycle de vie complétion/échec des tasks workflow."""
from __future__ import annotations

from uuid import uuid4

import pytest

pytestmark = pytest.mark.asyncio


async def test_mark_completed_sets_status_result_completed_at(
    fresh_db, mock_session_and_agent
):
    from agflow.services import tasks_service

    sid, aid = mock_session_and_agent
    cid = uuid4()
    task = await tasks_service.create_session_work(
        session_id=sid,
        agent_instance_id=aid,
        agflow_correlation_id=cid,
        instruction={"text": "x"},
    )

    await tasks_service.mark_completed(
        task_id=task["task_id"],
        result={"summary": "done", "artifacts": []},
    )

    row = await tasks_service.get_by_id(task["task_id"])
    assert row["status"] == "completed"
    assert row["result"] == {"summary": "done", "artifacts": []}
    assert row["error"] is None
    assert row["completed_at"] is not None


async def test_mark_failed_sets_status_error_completed_at(
    fresh_db, mock_session_and_agent
):
    from agflow.services import tasks_service

    sid, aid = mock_session_and_agent
    cid = uuid4()
    task = await tasks_service.create_session_work(
        session_id=sid,
        agent_instance_id=aid,
        agflow_correlation_id=cid,
        instruction={"text": "x"},
    )

    await tasks_service.mark_failed(
        task_id=task["task_id"],
        error={"code": "AGENT_OOM", "message": "out of memory"},
    )

    row = await tasks_service.get_by_id(task["task_id"])
    assert row["status"] == "failed"
    assert row["error"] == {"code": "AGENT_OOM", "message": "out of memory"}
    assert row["result"] is None
    assert row["completed_at"] is not None


async def test_mark_completed_unknown_task_raises(fresh_db):
    from agflow.services import tasks_service

    with pytest.raises(tasks_service.TaskNotFoundError):
        await tasks_service.mark_completed(task_id=uuid4(), result={"summary": "x"})


async def test_mark_failed_unknown_task_raises(fresh_db):
    from agflow.services import tasks_service

    with pytest.raises(tasks_service.TaskNotFoundError):
        await tasks_service.mark_failed(
            task_id=uuid4(), error={"code": "X", "message": "y"}
        )
