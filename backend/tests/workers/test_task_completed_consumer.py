"""Tests du consumer MOM task_completed (workflow tranche 3)."""
from __future__ import annotations

import json
from uuid import uuid4

import pytest

pytestmark = pytest.mark.asyncio


async def test_consumer_marks_task_completed_and_enqueues_hook(
    fresh_db, mock_session_with_callback, mock_hmac_key
):
    from agflow.services import tasks_service
    from agflow.workers import task_completed_consumer

    sid = mock_session_with_callback["session_id"]
    aid = mock_session_with_callback["agent_instance_id"]
    task = await tasks_service.create_session_work(
        session_id=sid,
        agent_instance_id=aid,
        agflow_correlation_id=uuid4(),
        instruction={"text": "x"},
    )
    await _publish_mom_result(
        fresh_db,
        session_id=sid,
        instance_id=aid,
        task_id=task["task_id"],
        payload={
            "_agflow_task_id": str(task["task_id"]),
            "result": {"summary": "done"},
        },
    )

    await task_completed_consumer.process_batch()

    row = await tasks_service.get_by_id(task["task_id"])
    assert row["status"] == "completed"

    hooks = await fresh_db.fetch(
        "SELECT * FROM outbound_hooks WHERE task_id = $1", task["task_id"]
    )
    assert len(hooks) == 1
    assert hooks[0]["status"] == "pending"


async def test_consumer_marks_task_failed_on_error_kind(
    fresh_db, mock_session_with_callback, mock_hmac_key
):
    from agflow.services import tasks_service
    from agflow.workers import task_completed_consumer

    sid = mock_session_with_callback["session_id"]
    aid = mock_session_with_callback["agent_instance_id"]
    task = await tasks_service.create_session_work(
        session_id=sid,
        agent_instance_id=aid,
        agflow_correlation_id=uuid4(),
        instruction={},
    )
    await _publish_mom_result(
        fresh_db,
        session_id=sid,
        instance_id=aid,
        task_id=task["task_id"],
        kind="error",
        payload={
            "_agflow_task_id": str(task["task_id"]),
            "error": {"code": "AGENT_OOM", "message": "oom"},
        },
    )

    await task_completed_consumer.process_batch()
    row = await tasks_service.get_by_id(task["task_id"])
    assert row["status"] == "failed"


async def test_consumer_ignores_message_without_agflow_task_id(
    fresh_db, mock_session_with_callback
):
    from agflow.workers import task_completed_consumer

    sid = mock_session_with_callback["session_id"]
    aid = mock_session_with_callback["agent_instance_id"]
    await _publish_mom_result(
        fresh_db,
        session_id=sid,
        instance_id=aid,
        task_id=uuid4(),
        payload={"result": {"summary": "non-workflow result"}},
    )
    await task_completed_consumer.process_batch()
    count = await fresh_db.fetchval("SELECT COUNT(*) FROM outbound_hooks")
    assert count == 0


async def test_consumer_skips_session_without_callback_url(
    fresh_db, mock_session_without_callback
):
    from agflow.services import tasks_service
    from agflow.workers import task_completed_consumer

    sid = mock_session_without_callback["session_id"]
    aid = mock_session_without_callback["agent_instance_id"]
    task = await tasks_service.create_session_work(
        session_id=sid,
        agent_instance_id=aid,
        agflow_correlation_id=uuid4(),
        instruction={},
    )
    await _publish_mom_result(
        fresh_db,
        session_id=sid,
        instance_id=aid,
        task_id=task["task_id"],
        payload={
            "_agflow_task_id": str(task["task_id"]),
            "result": {"summary": "x"},
        },
    )
    await task_completed_consumer.process_batch()

    row = await tasks_service.get_by_id(task["task_id"])
    assert row["status"] == "completed"
    count = await fresh_db.fetchval(
        "SELECT COUNT(*) FROM outbound_hooks WHERE task_id = $1", task["task_id"]
    )
    assert count == 0


async def test_consumer_idempotent_on_double_claim(
    fresh_db, mock_session_with_callback, mock_hmac_key
):
    from agflow.services import tasks_service
    from agflow.workers import task_completed_consumer

    sid = mock_session_with_callback["session_id"]
    aid = mock_session_with_callback["agent_instance_id"]
    task = await tasks_service.create_session_work(
        session_id=sid,
        agent_instance_id=aid,
        agflow_correlation_id=uuid4(),
        instruction={},
    )
    await _publish_mom_result(
        fresh_db,
        session_id=sid,
        instance_id=aid,
        task_id=task["task_id"],
        payload={
            "_agflow_task_id": str(task["task_id"]),
            "result": {"summary": "x"},
        },
    )
    await task_completed_consumer.process_batch()

    # Force le 2e claim en remettant le message pending
    await fresh_db.execute(
        "UPDATE agent_message_delivery SET status='pending', acked_at=NULL "
        "WHERE group_name = 'workflow_task_completed'"
    )
    await task_completed_consumer.process_batch()

    count = await fresh_db.fetchval(
        "SELECT COUNT(*) FROM outbound_hooks WHERE task_id = $1", task["task_id"]
    )
    assert count == 1  # idempotence : pas de 2e hook


async def _publish_mom_result(
    fresh_db,
    *,
    session_id,
    instance_id,
    task_id,
    payload: dict,
    kind: str = "result",
) -> None:
    """Insère manuellement un message agent_messages OUT + agent_message_delivery
    pour simuler la publication par un agent.
    """
    msg_id = await fresh_db.fetchval(
        """
        INSERT INTO agent_messages
        (session_id, instance_id, direction, kind, payload, source)
        VALUES ($1::text, $2::text, 'out', $3, $4::jsonb, 'test')
        RETURNING msg_id
        """,
        str(session_id),
        str(instance_id),
        kind,
        json.dumps(payload),
    )
    await fresh_db.execute(
        "INSERT INTO agent_message_delivery (group_name, msg_id, status) "
        "VALUES ('workflow_task_completed', $1, 'pending')",
        msg_id,
    )
