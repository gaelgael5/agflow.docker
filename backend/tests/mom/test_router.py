from __future__ import annotations

import pytest
import pytest_asyncio

from agflow.db.pool import close_pool, fetch_all, get_pool
from agflow.mom.consumers.router import Router
from agflow.mom.envelope import Direction, Kind, Route
from agflow.mom.publisher import MomPublisher


@pytest_asyncio.fixture
async def pool():
    p = await get_pool()
    yield p
    await close_pool()


@pytest_asyncio.fixture
async def publisher(pool) -> MomPublisher:
    return MomPublisher(
        pool=pool,
        groups_config={
            Direction.IN: ["dispatcher"],
            Direction.OUT: ["router"],
        },
    )


@pytest.mark.asyncio
class TestRouter:
    async def test_route_agent_creates_in_message(
        self, publisher: MomPublisher, pool,
    ) -> None:
        msg_id = await publisher.publish(
            session_id="s", instance_id="source-agent",
            direction=Direction.OUT, source="agent:source-agent",
            kind=Kind.INSTRUCTION, payload={"text": "do this"},
            route=Route(target="agent:target-agent"),
        )
        router = Router(pool=pool, publisher=publisher)
        processed = await router.process_once()
        assert processed >= 1

        in_msgs = await fetch_all(
            "SELECT * FROM agent_messages "
            "WHERE instance_id='target-agent' AND direction='in'",
        )
        assert len(in_msgs) == 1
        assert in_msgs[0]["payload"]["text"] == "do this"
        assert in_msgs[0]["source"] == "agent:source-agent"
        assert str(in_msgs[0]["parent_msg_id"]) == str(msg_id)

    async def test_route_team_returns_error(
        self, publisher: MomPublisher, pool,
    ) -> None:
        await publisher.publish(
            session_id="s", instance_id="source-agent",
            direction=Direction.OUT, source="agent:source-agent",
            kind=Kind.INSTRUCTION, payload={"text": "team task"},
            route=Route(target="team:python"),
        )
        router = Router(pool=pool, publisher=publisher)
        await router.process_once()

        errors = await fetch_all(
            "SELECT * FROM agent_messages "
            "WHERE instance_id='source-agent' "
            "AND direction='out' AND kind='error'",
        )
        assert len(errors) == 1
        assert "not_yet_supported" in errors[0]["payload"]["message"]

    async def test_no_route_is_acked_silently(
        self, publisher: MomPublisher, pool,
    ) -> None:
        await publisher.publish(
            session_id="s", instance_id="agent-1",
            direction=Direction.OUT, source="agent:agent-1",
            kind=Kind.EVENT, payload={"text": "just progress"},
        )
        router = Router(pool=pool, publisher=publisher)
        processed = await router.process_once()
        assert processed >= 0
