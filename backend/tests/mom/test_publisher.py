from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio

from agflow.db.pool import close_pool, execute, fetch_all, fetch_one, get_pool
from agflow.mom.envelope import Direction, Kind, Route
from agflow.mom.publisher import MomPublisher
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
async def publisher(pool) -> MomPublisher:
    groups_config = {
        Direction.IN: ["dispatcher"],
        Direction.OUT: ["ws_push", "router"],
    }
    return MomPublisher(pool=pool, groups_config=groups_config)


@pytest.mark.asyncio
class TestMomPublisher:
    async def test_publish_inserts_message_and_delivery(
        self,
        publisher: MomPublisher,
    ) -> None:
        msg_id = await publisher.publish(
            session_id="sess-test",
            instance_id="inst-test",
            direction=Direction.IN,
            source="test",
            kind=Kind.INSTRUCTION,
            payload={"text": "hello"},
        )
        assert msg_id is not None

        row = await fetch_one(
            "SELECT * FROM agent_messages WHERE msg_id = $1",
            msg_id,
        )
        assert row is not None
        assert row["kind"] == "instruction"
        assert row["direction"] == "in"
        assert row["payload"] == {"text": "hello"}

        deliveries = await fetch_all(
            "SELECT * FROM agent_message_delivery WHERE msg_id = $1",
            msg_id,
        )
        assert len(deliveries) == 1
        assert deliveries[0]["group_name"] == "dispatcher"
        assert deliveries[0]["status"] == "pending"

    async def test_publish_out_creates_deliveries_for_out_groups(
        self,
        publisher: MomPublisher,
    ) -> None:
        msg_id = await publisher.publish(
            session_id="sess-test",
            instance_id="inst-test",
            direction=Direction.OUT,
            source="agent:inst-test",
            kind=Kind.EVENT,
            payload={"text": "progress"},
        )
        deliveries = await fetch_all(
            "SELECT group_name FROM agent_message_delivery WHERE msg_id = $1 ORDER BY group_name",
            msg_id,
        )
        groups = [d["group_name"] for d in deliveries]
        assert groups == ["router", "ws_push"]

    async def test_publish_with_route_and_parent(
        self,
        publisher: MomPublisher,
    ) -> None:
        parent_id = await publisher.publish(
            session_id="sess-test",
            instance_id="inst-test",
            direction=Direction.IN,
            source="test",
            kind=Kind.INSTRUCTION,
            payload={"text": "root"},
        )
        child_id = await publisher.publish(
            session_id="sess-test",
            instance_id="inst-test",
            direction=Direction.OUT,
            source="agent:inst-test",
            kind=Kind.INSTRUCTION,
            payload={"text": "delegate"},
            parent_msg_id=parent_id,
            route=Route(target="agent:other-inst"),
        )
        row = await fetch_one(
            "SELECT parent_msg_id, route FROM agent_messages WHERE msg_id = $1",
            child_id,
        )
        assert str(row["parent_msg_id"]) == str(parent_id)
        assert row["route"]["target"] == "agent:other-inst"

    async def test_publish_instruction_in_marks_instance_busy(
        self,
        publisher: MomPublisher,
    ) -> None:
        # Setup : api_key + session + agent_catalog + instance réels
        api_key_id = uuid4()
        await execute(
            "INSERT INTO api_keys (id, owner_id, name, prefix, key_hash, scopes) "
            "VALUES ($1, $2, 'test-pub', $3, 'hash', $4)",
            api_key_id,
            uuid4(),
            f"pfx_{str(api_key_id)[:8]}",
            ["read"],
        )
        slug = f"test-agent-{uuid4().hex[:8]}"
        await agents_catalog_service.upsert(slug)
        session = await sessions_service.create(
            api_key_id=api_key_id,
            name=None,
            duration_seconds=3600,
        )
        ids = await agents_instances_service.create(
            session_id=session["id"],
            agent_id=slug,
            count=1,
            labels={},
            mission=None,
        )
        instance_id = ids[0]

        try:
            await publisher.publish(
                session_id=str(session["id"]),
                instance_id=str(instance_id),
                direction=Direction.IN,
                source="test",
                kind=Kind.INSTRUCTION,
                payload={"text": "run"},
            )
            row = await fetch_one(
                "SELECT status, last_activity_at FROM agents_instances WHERE id = $1",
                instance_id,
            )
            assert row["status"] == "busy"
            assert row["last_activity_at"] is not None
        finally:
            await sessions_service.close(
                session_id=session["id"],
                api_key_id=api_key_id,
                is_admin=False,
            )
            await execute("DELETE FROM api_keys WHERE id = $1", api_key_id)
            await agents_catalog_service.delete(slug)

    async def test_publish_out_updates_activity_but_not_status(
        self,
        publisher: MomPublisher,
    ) -> None:
        api_key_id = uuid4()
        await execute(
            "INSERT INTO api_keys (id, owner_id, name, prefix, key_hash, scopes) "
            "VALUES ($1, $2, 'test-pub-out', $3, 'hash', $4)",
            api_key_id,
            uuid4(),
            f"pfx_{str(api_key_id)[:8]}",
            ["read"],
        )
        slug = f"test-agent-{uuid4().hex[:8]}"
        await agents_catalog_service.upsert(slug)
        session = await sessions_service.create(
            api_key_id=api_key_id,
            name=None,
            duration_seconds=3600,
        )
        ids = await agents_instances_service.create(
            session_id=session["id"],
            agent_id=slug,
            count=1,
            labels={},
            mission=None,
        )
        instance_id = ids[0]

        try:
            # Part idle, OUT event ne doit pas basculer en busy
            before = await fetch_one(
                "SELECT status, last_activity_at FROM agents_instances WHERE id = $1",
                instance_id,
            )
            assert before["status"] == "idle"
            await publisher.publish(
                session_id=str(session["id"]),
                instance_id=str(instance_id),
                direction=Direction.OUT,
                source=f"agent:{instance_id}",
                kind=Kind.EVENT,
                payload={"progress": 0.5},
            )
            after = await fetch_one(
                "SELECT status, last_activity_at FROM agents_instances WHERE id = $1",
                instance_id,
            )
            assert after["status"] == "idle"
            assert after["last_activity_at"] >= before["last_activity_at"]
        finally:
            await sessions_service.close(
                session_id=session["id"],
                api_key_id=api_key_id,
                is_admin=False,
            )
            await execute("DELETE FROM api_keys WHERE id = $1", api_key_id)
            await agents_catalog_service.delete(slug)
