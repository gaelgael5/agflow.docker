from __future__ import annotations

import json
from uuid import UUID

import asyncpg
import structlog

from agflow.mom.envelope import Direction, Kind, Route

_log = structlog.get_logger(__name__)

_INSERT_MSG = """
INSERT INTO agent_messages
    (session_id, instance_id, direction, kind, payload, route, source, parent_msg_id)
VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7, $8)
RETURNING msg_id
"""

_INSERT_DELIVERY = """
INSERT INTO agent_message_delivery (group_name, msg_id, status)
VALUES ($1, $2, 'pending')
"""

_NOTIFY = "SELECT pg_notify($1, $2)"


class MomPublisher:
    def __init__(
        self,
        pool: asyncpg.Pool,
        groups_config: dict[Direction, list[str]],
    ) -> None:
        self._pool = pool
        self._groups_config = groups_config

    async def publish(
        self,
        *,
        session_id: str,
        instance_id: str,
        direction: Direction,
        source: str,
        kind: Kind,
        payload: dict,
        route: Route | None = None,
        parent_msg_id: str | UUID | None = None,
        conn: asyncpg.Connection | None = None,
    ) -> UUID:
        route_json = json.dumps(route.model_dump()) if route else None
        payload_json = json.dumps(payload, ensure_ascii=False)
        parent = UUID(str(parent_msg_id)) if parent_msg_id else None

        groups = self._groups_config.get(direction, [])

        async def _do(c: asyncpg.Connection) -> UUID:
            msg_id: UUID = await c.fetchval(
                _INSERT_MSG,
                session_id, instance_id, str(direction), str(kind),
                payload_json, route_json, source, parent,
            )
            for g in groups:
                await c.execute(_INSERT_DELIVERY, g, msg_id)
            channel = f"mom_{instance_id}_{direction}"
            await c.execute(_NOTIFY, channel, str(msg_id))
            _log.info(
                "mom.published",
                msg_id=str(msg_id),
                direction=str(direction),
                kind=str(kind),
                instance_id=instance_id,
            )
            return msg_id

        if conn is not None:
            return await _do(conn)
        async with self._pool.acquire() as c, c.transaction():
            return await _do(c)
