"""Tests de tasks_service."""
from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
from asyncpg import Connection

from agflow.db.pool import get_pool
from tests._db_reset import reset_schema_and_migrate

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def fresh_db() -> AsyncIterator[Connection]:
    await reset_schema_and_migrate()
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


@pytest.fixture
async def mock_session_and_agent(fresh_db: Connection) -> tuple[UUID, UUID]:
    """Crée une api_key + session + agent_instance valides via INSERT direct."""
    # API key
    api_key_id = uuid4()
    await fresh_db.execute(
        """
        INSERT INTO api_keys (id, name, prefix, key_hash, scopes)
        VALUES ($1, 'test', 'agfd_test', 'bcrypt-hash', '{m2m:orchestrate}')
        """,
        api_key_id,
    )
    # Agents catalog entry (FK)
    await fresh_db.execute(
        """
        INSERT INTO agents_catalog (slug)
        VALUES ('claude-r1')
        ON CONFLICT DO NOTHING
        """,
    )
    # Session
    session_id = uuid4()
    await fresh_db.execute(
        """
        INSERT INTO sessions (id, api_key_id, expires_at)
        VALUES ($1, $2, now() + interval '1 hour')
        """,
        session_id,
        api_key_id,
    )
    # Agent instance
    agent_instance_id = uuid4()
    await fresh_db.execute(
        """
        INSERT INTO agents_instances (id, session_id, agent_id, labels)
        VALUES ($1, $2, 'claude-r1', '{}'::jsonb)
        """,
        agent_instance_id,
        session_id,
    )
    return session_id, agent_instance_id


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
