"""Tests des publishers supervision_events (pg_notify channel)."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_pool():
    pool = AsyncMock()
    return pool


async def test_publish_instance_created_calls_pg_notify(mock_pool):
    from agflow.services import supervision_events

    iid = uuid4()
    sid = uuid4()
    with patch("agflow.services.supervision_events.get_pool", return_value=mock_pool):
        await supervision_events.publish_instance_created(
            instance_id=iid, session_id=sid
        )

    mock_pool.execute.assert_awaited_once()
    args = mock_pool.execute.await_args.args
    assert args[0] == "SELECT pg_notify($1, $2)"
    assert args[1] == "supervision_events"
    payload = json.loads(args[2])
    assert payload == {
        "type": "instance.created",
        "id": str(iid),
        "session_id": str(sid),
    }


async def test_publish_instance_status_changed(mock_pool):
    from agflow.services import supervision_events

    iid = uuid4()
    with patch("agflow.services.supervision_events.get_pool", return_value=mock_pool):
        await supervision_events.publish_instance_status_changed(instance_id=iid)

    args = mock_pool.execute.await_args.args
    assert json.loads(args[2]) == {"type": "instance.status_changed", "id": str(iid)}


async def test_publish_instance_destroyed(mock_pool):
    from agflow.services import supervision_events

    iid = uuid4()
    with patch("agflow.services.supervision_events.get_pool", return_value=mock_pool):
        await supervision_events.publish_instance_destroyed(instance_id=iid)

    args = mock_pool.execute.await_args.args
    assert json.loads(args[2]) == {"type": "instance.destroyed", "id": str(iid)}


async def test_publish_session_created(mock_pool):
    from agflow.services import supervision_events

    sid = uuid4()
    with patch("agflow.services.supervision_events.get_pool", return_value=mock_pool):
        await supervision_events.publish_session_created(session_id=sid)

    args = mock_pool.execute.await_args.args
    assert json.loads(args[2]) == {"type": "session.created", "id": str(sid)}


async def test_publish_session_closed_with_status(mock_pool):
    from agflow.services import supervision_events

    sid = uuid4()
    with patch("agflow.services.supervision_events.get_pool", return_value=mock_pool):
        await supervision_events.publish_session_closed(
            session_id=sid, status="expired"
        )

    args = mock_pool.execute.await_args.args
    assert json.loads(args[2]) == {
        "type": "session.closed",
        "id": str(sid),
        "status": "expired",
    }


async def test_publish_swallows_db_errors(mock_pool, caplog):
    """Les publishers ne propagent jamais l'erreur DB (mutation reste atomique)."""
    from agflow.services import supervision_events

    mock_pool.execute.side_effect = RuntimeError("DB down")
    with patch("agflow.services.supervision_events.get_pool", return_value=mock_pool):
        # Ne doit PAS lever
        await supervision_events.publish_instance_destroyed(instance_id=uuid4())
