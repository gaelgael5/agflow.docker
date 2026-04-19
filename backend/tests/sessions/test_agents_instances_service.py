from __future__ import annotations

import json
from uuid import UUID, uuid4

import pytest
import pytest_asyncio

from agflow.db.pool import close_pool, execute, fetch_one, get_pool
from agflow.services import (
    agents_catalog_service,
    agents_instances_service,
    sessions_service,
)


@pytest_asyncio.fixture
async def pool():
    p = await get_pool()
    yield p
    await close_pool()


@pytest_asyncio.fixture
async def api_key_id(pool) -> UUID:
    kid = uuid4()
    await execute(
        "INSERT INTO api_keys (id, owner_id, name, prefix, key_hash, scopes) "
        "VALUES ($1, $2, 'test', $3, 'hash', $4)",
        kid, uuid4(), f"pfx_{str(kid)[:8]}", ["read"],
    )
    await agents_catalog_service.upsert("test-agent")
    yield kid
    await execute("DELETE FROM api_keys WHERE id = $1", kid)
    await agents_catalog_service.delete("test-agent")


@pytest.mark.asyncio
class TestAgentsInstancesService:
    async def test_create_single_instance(self, api_key_id: UUID) -> None:
        session = await sessions_service.create(
            api_key_id=api_key_id, name=None, duration_seconds=3600,
        )
        ids = await agents_instances_service.create(
            session_id=session["id"], agent_id="test-agent",
            count=1, labels={"team": "x"}, mission="do stuff",
        )
        assert len(ids) == 1

        row = await fetch_one(
            "SELECT agent_id, labels, mission FROM agents_instances WHERE id = $1",
            ids[0],
        )
        assert row["agent_id"] == "test-agent"
        labels = row["labels"] if isinstance(row["labels"], dict) else json.loads(row["labels"])
        assert labels == {"team": "x"}
        await sessions_service.close(
            session_id=session["id"], api_key_id=api_key_id, is_admin=False,
        )

    async def test_create_multiple_instances(self, api_key_id: UUID) -> None:
        session = await sessions_service.create(
            api_key_id=api_key_id, name=None, duration_seconds=3600,
        )
        ids = await agents_instances_service.create(
            session_id=session["id"], agent_id="test-agent",
            count=3, labels={}, mission=None,
        )
        assert len(ids) == 3
        assert len(set(ids)) == 3
        await sessions_service.close(
            session_id=session["id"], api_key_id=api_key_id, is_admin=False,
        )

    async def test_list_active_only(self, api_key_id: UUID) -> None:
        session = await sessions_service.create(
            api_key_id=api_key_id, name=None, duration_seconds=3600,
        )
        ids = await agents_instances_service.create(
            session_id=session["id"], agent_id="test-agent",
            count=2, labels={}, mission=None,
        )
        await agents_instances_service.destroy(
            session_id=session["id"], instance_id=ids[0],
        )
        active = await agents_instances_service.list_for_session(
            session_id=session["id"],
        )
        assert len(active) == 1
        assert active[0]["id"] == ids[1]
        await sessions_service.close(
            session_id=session["id"], api_key_id=api_key_id, is_admin=False,
        )

    async def test_status_is_idle_when_no_pending_instructions(
        self, api_key_id: UUID,
    ) -> None:
        session = await sessions_service.create(
            api_key_id=api_key_id, name=None, duration_seconds=3600,
        )
        await agents_instances_service.create(
            session_id=session["id"], agent_id="test-agent",
            count=1, labels={}, mission=None,
        )
        active = await agents_instances_service.list_for_session(
            session_id=session["id"],
        )
        assert active[0]["status"] == "idle"
        await sessions_service.close(
            session_id=session["id"], api_key_id=api_key_id, is_admin=False,
        )

    async def test_status_is_busy_when_pending_instruction(
        self, api_key_id: UUID,
    ) -> None:
        session = await sessions_service.create(
            api_key_id=api_key_id, name=None, duration_seconds=3600,
        )
        ids = await agents_instances_service.create(
            session_id=session["id"], agent_id="test-agent",
            count=1, labels={}, mission=None,
        )
        await execute(
            "INSERT INTO agent_messages "
            "(session_id, instance_id, direction, kind, payload, source) "
            "VALUES ($1, $2, 'in', 'instruction', '{}'::jsonb, 'test')",
            str(session["id"]), str(ids[0]),
        )
        await execute(
            "INSERT INTO agent_message_delivery (group_name, msg_id, status) "
            "SELECT 'dispatcher', msg_id, 'pending' FROM agent_messages "
            "WHERE instance_id = $1",
            str(ids[0]),
        )
        active = await agents_instances_service.list_for_session(
            session_id=session["id"],
        )
        assert active[0]["status"] == "busy"
        await sessions_service.close(
            session_id=session["id"], api_key_id=api_key_id, is_admin=False,
        )

    async def test_destroy_marks_destroyed_at(self, api_key_id: UUID) -> None:
        session = await sessions_service.create(
            api_key_id=api_key_id, name=None, duration_seconds=3600,
        )
        ids = await agents_instances_service.create(
            session_id=session["id"], agent_id="test-agent",
            count=1, labels={}, mission=None,
        )
        ok = await agents_instances_service.destroy(
            session_id=session["id"], instance_id=ids[0],
        )
        assert ok is True
        row = await fetch_one(
            "SELECT destroyed_at FROM agents_instances WHERE id = $1", ids[0],
        )
        assert row["destroyed_at"] is not None
        await sessions_service.close(
            session_id=session["id"], api_key_id=api_key_id, is_admin=False,
        )
