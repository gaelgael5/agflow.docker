from __future__ import annotations

from typing import Any, Protocol

import structlog

from agflow.mom.adapters.base import AgentAdapter
from agflow.mom.consumer import MomConsumer
from agflow.mom.envelope import Direction
from agflow.mom.publisher import MomPublisher

_log = structlog.get_logger(__name__)


class ContainerIO(Protocol):
    async def write_stdin(self, data: bytes) -> None: ...
    def iter_stdout(self) -> Any: ...
    async def wait(self) -> int: ...


class AgentDispatcher:
    def __init__(
        self,
        *,
        adapter: AgentAdapter,
        publisher: MomPublisher,
        consumer: MomConsumer,
        container: ContainerIO,
        session_id: str,
        instance_id: str,
    ) -> None:
        self._adapter = adapter
        self._publisher = publisher
        self._consumer = consumer
        self._container = container
        self._session_id = session_id
        self._instance_id = instance_id

    async def run(self) -> None:
        envelopes = await self._consumer.claim_batch(
            instance_id=self._instance_id,
            direction=Direction.IN,
            batch_size=1,
        )
        if not envelopes:
            _log.warning(
                "dispatcher.no_instruction", instance_id=self._instance_id,
            )
            return

        instruction = envelopes[0]
        parent_msg_id = instruction.msg_id

        stdin_bytes = self._adapter.format_stdin(instruction)
        await self._container.write_stdin(stdin_bytes)
        await self._consumer.ack(instruction.msg_id)

        _log.info(
            "dispatcher.instruction_sent",
            instance_id=self._instance_id,
            msg_id=str(instruction.msg_id),
        )

        async for line in self._container.iter_stdout():
            if not line or not line.strip():
                continue
            result = self._adapter.parse_stdout_line(line.strip())
            if result is None:
                continue
            kind, payload, route = result
            await self._publisher.publish(
                session_id=self._session_id,
                instance_id=self._instance_id,
                direction=Direction.OUT,
                source=f"agent:{self._instance_id}",
                kind=kind,
                payload=payload,
                route=route,
                parent_msg_id=parent_msg_id,
            )

        exit_code = await self._container.wait()
        _log.info(
            "dispatcher.container_exited",
            instance_id=self._instance_id,
            exit_code=exit_code,
        )
