from __future__ import annotations

import asyncio

import asyncpg
import structlog

from agflow.mom.consumer import MomConsumer
from agflow.mom.envelope import Direction

_log = structlog.get_logger(__name__)


class WsPushConsumer:
    def __init__(
        self,
        pool: asyncpg.Pool,
        instance_id: str,
        connection_id: str,
    ) -> None:
        self._group_name = "ws_push"
        self._consumer = MomConsumer(
            pool=pool,
            group_name=self._group_name,
            consumer_id=f"ws-{connection_id}",
        )
        self._instance_id = instance_id

    async def iter_events(self):
        while True:
            envelopes = await self._consumer.claim_batch(
                instance_id=self._instance_id,
                direction=Direction.OUT,
                batch_size=20,
            )
            for env in envelopes:
                yield env.model_dump(mode="json")
                await self._consumer.ack(env.msg_id)
            if not envelopes:
                await asyncio.sleep(0.1)
