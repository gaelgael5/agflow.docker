from __future__ import annotations

import asyncpg
import structlog

from agflow.mom.consumer import MomConsumer
from agflow.mom.envelope import Direction, Kind
from agflow.mom.publisher import MomPublisher

_log = structlog.get_logger(__name__)

_SUPPORTED_PREFIXES = ("agent:",)
_KNOWN_PREFIXES = ("agent:", "team:", "pool:", "session:")


class Router:
    def __init__(self, pool: asyncpg.Pool, publisher: MomPublisher) -> None:
        self._consumer = MomConsumer(
            pool=pool, group_name="router", consumer_id="router-main",
        )
        self._publisher = publisher

    async def process_once(self) -> int:
        envelopes = await self._consumer.claim_batch(
            direction=Direction.OUT, batch_size=50,
        )
        for env in envelopes:
            if env.route is None:
                await self._consumer.ack(env.msg_id)
                continue

            target = env.route.target
            prefix = next(
                (p for p in _KNOWN_PREFIXES if target.startswith(p)), None,
            )

            if prefix and prefix in _SUPPORTED_PREFIXES:
                target_instance = target[len(prefix):]
                await self._publisher.publish(
                    session_id=env.session_id,
                    instance_id=target_instance,
                    direction=Direction.IN,
                    source=env.source,
                    kind=env.kind,
                    payload=env.payload,
                    parent_msg_id=env.msg_id,
                )
                _log.info(
                    "router.dispatched",
                    from_instance=env.instance_id,
                    to_instance=target_instance,
                    msg_id=str(env.msg_id),
                )
            else:
                await self._publisher.publish(
                    session_id=env.session_id,
                    instance_id=env.instance_id,
                    direction=Direction.OUT,
                    source="system",
                    kind=Kind.ERROR,
                    payload={
                        "message": f"route_type_not_yet_supported: {target}",
                        "target": target,
                    },
                    parent_msg_id=env.msg_id,
                )
                _log.warning("router.unsupported_prefix", target=target)

            await self._consumer.ack(env.msg_id)

        return len(envelopes)
