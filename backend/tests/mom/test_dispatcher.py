from __future__ import annotations

import json

import pytest
import pytest_asyncio

from agflow.db.pool import close_pool, fetch_all, get_pool
from agflow.mom.adapters.generic import GenericAdapter
from agflow.mom.consumer import MomConsumer
from agflow.mom.dispatcher import AgentDispatcher
from agflow.mom.envelope import Direction, Kind
from agflow.mom.publisher import MomPublisher


class FakeContainer:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.stdin_received: bytes = b""
        self._exit_code = 0

    async def write_stdin(self, data: bytes) -> None:
        self.stdin_received += data

    async def iter_stdout(self):
        for line in self._responses:
            yield line

    async def wait(self) -> int:
        return self._exit_code


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
            Direction.OUT: ["ws_push", "router"],
        },
    )


@pytest.mark.asyncio
class TestAgentDispatcher:
    async def test_full_flow(self, publisher: MomPublisher, pool) -> None:
        await publisher.publish(
            session_id="s1", instance_id="inst-1",
            direction=Direction.IN, source="test",
            kind=Kind.INSTRUCTION, payload={"text": "hello agent"},
        )

        container = FakeContainer(responses=[
            json.dumps({"kind": "event", "payload": {"text": "working..."}}),
            json.dumps({
                "kind": "result",
                "payload": {"status": "success", "exit_code": 0},
            }),
        ])

        consumer = MomConsumer(
            pool=pool, group_name="dispatcher", consumer_id="d1",
        )
        dispatcher = AgentDispatcher(
            adapter=GenericAdapter(),
            publisher=publisher,
            consumer=consumer,
            container=container,
            session_id="s1",
            instance_id="inst-1",
        )

        await dispatcher.run()

        assert container.stdin_received != b""
        stdin_data = json.loads(container.stdin_received.decode().strip())
        assert stdin_data["payload"]["text"] == "hello agent"

        out_msgs = await fetch_all(
            "SELECT kind, payload FROM agent_messages "
            "WHERE instance_id='inst-1' AND direction='out' "
            "ORDER BY created_at",
        )
        assert len(out_msgs) == 2
        assert out_msgs[0]["kind"] == "event"
        assert out_msgs[1]["kind"] == "result"

    async def test_no_instruction_returns_silently(
        self, publisher: MomPublisher, pool,
    ) -> None:
        container = FakeContainer(responses=[])
        consumer = MomConsumer(
            pool=pool, group_name="dispatcher", consumer_id="d2",
        )
        dispatcher = AgentDispatcher(
            adapter=GenericAdapter(),
            publisher=publisher,
            consumer=consumer,
            container=container,
            session_id="s-empty",
            instance_id="inst-empty",
        )
        await dispatcher.run()
        assert container.stdin_received == b""

    async def test_raw_lines_wrapped_as_event(
        self, publisher: MomPublisher, pool,
    ) -> None:
        await publisher.publish(
            session_id="s2", instance_id="inst-2",
            direction=Direction.IN, source="test",
            kind=Kind.INSTRUCTION, payload={"text": "go"},
        )
        container = FakeContainer(responses=[
            "plain log line without json",
            "another one",
        ])
        consumer = MomConsumer(
            pool=pool, group_name="dispatcher", consumer_id="d3",
        )
        dispatcher = AgentDispatcher(
            adapter=GenericAdapter(),
            publisher=publisher,
            consumer=consumer,
            container=container,
            session_id="s2",
            instance_id="inst-2",
        )
        await dispatcher.run()

        out_msgs = await fetch_all(
            "SELECT payload FROM agent_messages "
            "WHERE instance_id='inst-2' AND direction='out' "
            "ORDER BY created_at",
        )
        assert len(out_msgs) == 2
        assert out_msgs[0]["payload"]["format"] == "raw"
