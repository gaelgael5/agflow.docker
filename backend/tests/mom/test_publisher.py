from __future__ import annotations

import pytest
import pytest_asyncio

from agflow.db.pool import close_pool, fetch_all, fetch_one, get_pool
from agflow.mom.envelope import Direction, Kind, Route
from agflow.mom.publisher import MomPublisher


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
        self, publisher: MomPublisher,
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
            "SELECT * FROM agent_messages WHERE msg_id = $1", msg_id,
        )
        assert row is not None
        assert row["kind"] == "instruction"
        assert row["direction"] == "in"
        assert row["payload"] == {"text": "hello"}

        deliveries = await fetch_all(
            "SELECT * FROM agent_message_delivery WHERE msg_id = $1", msg_id,
        )
        assert len(deliveries) == 1
        assert deliveries[0]["group_name"] == "dispatcher"
        assert deliveries[0]["status"] == "pending"

    async def test_publish_out_creates_deliveries_for_out_groups(
        self, publisher: MomPublisher,
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
            "SELECT group_name FROM agent_message_delivery "
            "WHERE msg_id = $1 ORDER BY group_name",
            msg_id,
        )
        groups = [d["group_name"] for d in deliveries]
        assert groups == ["router", "ws_push"]

    async def test_publish_with_route_and_parent(
        self, publisher: MomPublisher,
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
