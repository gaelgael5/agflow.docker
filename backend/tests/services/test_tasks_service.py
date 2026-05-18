"""Tests de tasks_service."""
from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from asyncpg import Connection

pytestmark = pytest.mark.asyncio


async def test_create_session_work_inserts_pending(
    fresh_db: Connection, mock_session_and_agent: tuple[UUID, UUID]
):
    from agflow.services import tasks_service

    sid, aid = mock_session_and_agent
    cid = uuid4()
    task = await tasks_service.create_session_work(
        session_id=sid,
        agent_instance_id=aid,
        agflow_correlation_id=cid,
        instruction={"text": "do something"},
    )
    assert task["status"] == "pending"
    assert task["kind"] == "session_work"
    assert task["agflow_correlation_id"] == cid
    assert task["was_existing"] is False


async def test_create_session_work_idempotent(
    fresh_db: Connection, mock_session_and_agent: tuple[UUID, UUID]
):
    from agflow.services import tasks_service

    sid, aid = mock_session_and_agent
    cid = uuid4()
    first = await tasks_service.create_session_work(
        session_id=sid,
        agent_instance_id=aid,
        agflow_correlation_id=cid,
        instruction={"text": "first"},
    )
    second = await tasks_service.create_session_work(
        session_id=sid,
        agent_instance_id=aid,
        agflow_correlation_id=cid,
        instruction={"text": "second"},  # ignored
    )
    assert first["task_id"] == second["task_id"]
    assert second["was_existing"] is True


async def test_get_by_id_returns_task(
    fresh_db: Connection, mock_session_and_agent: tuple[UUID, UUID]
):
    from agflow.services import tasks_service

    sid, aid = mock_session_and_agent
    cid = uuid4()
    created = await tasks_service.create_session_work(
        session_id=sid,
        agent_instance_id=aid,
        agflow_correlation_id=cid,
        instruction={"x": 1},
    )
    got = await tasks_service.get_by_id(created["task_id"])
    assert got is not None
    assert got["task_id"] == created["task_id"]


async def test_get_by_id_unknown_returns_none(fresh_db: Connection):
    from agflow.services import tasks_service

    got = await tasks_service.get_by_id(uuid4())
    assert got is None
