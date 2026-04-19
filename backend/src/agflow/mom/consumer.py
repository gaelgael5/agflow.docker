from __future__ import annotations

from datetime import timedelta
from uuid import UUID

import asyncpg
import structlog

from agflow.mom.envelope import Direction, Envelope, Kind, Route

_log = structlog.get_logger(__name__)

_CLAIM_SQL = """
WITH claimable AS (
    SELECT d.msg_id
    FROM agent_message_delivery d
    JOIN agent_messages m USING (msg_id)
    WHERE d.group_name = $1
      AND d.status = 'pending'
      AND ($2::text IS NULL OR m.instance_id = $2)
      AND ($3::text IS NULL OR m.direction = $3)
    ORDER BY m.created_at
    FOR UPDATE OF d SKIP LOCKED
    LIMIT $4
)
UPDATE agent_message_delivery d
SET status = 'claimed', claimed_at = now(), claimed_by = $5
FROM claimable
WHERE d.group_name = $1 AND d.msg_id = claimable.msg_id
RETURNING d.msg_id
"""

_FETCH_MSGS = """
SELECT msg_id, parent_msg_id, v, session_id, instance_id, direction,
       kind, payload, route, source, created_at
FROM agent_messages
WHERE msg_id = ANY($1::uuid[])
ORDER BY created_at
"""

_ACK_SQL = """
UPDATE agent_message_delivery SET status = 'acked', acked_at = now()
WHERE group_name = $1 AND msg_id = $2
"""

_FAIL_SQL = """
UPDATE agent_message_delivery
SET status = CASE WHEN retry_count + 1 >= $3 THEN 'failed' ELSE 'pending' END,
    retry_count = retry_count + 1,
    last_error = $4,
    claimed_at = NULL,
    claimed_by = NULL
WHERE group_name = $1 AND msg_id = $2
"""

_RECLAIM_SQL = """
UPDATE agent_message_delivery
SET status = 'pending', claimed_at = NULL, claimed_by = NULL
WHERE status = 'claimed' AND claimed_at < now() - $1::interval
  AND group_name = $2
"""

MAX_RETRIES = 3


def _decode_jsonb(value: object) -> object:
    if isinstance(value, str):
        import json
        return json.loads(value)
    return value


def _row_to_envelope(row: asyncpg.Record) -> Envelope:
    route_data = _decode_jsonb(row["route"])
    route = Route.model_validate(route_data) if route_data else None
    payload = _decode_jsonb(row["payload"])
    return Envelope(
        v=row["v"],
        msg_id=str(row["msg_id"]),
        parent_msg_id=str(row["parent_msg_id"]) if row["parent_msg_id"] else None,
        session_id=row["session_id"],
        instance_id=row["instance_id"],
        direction=Direction(row["direction"]),
        timestamp=row["created_at"],
        source=row["source"],
        kind=Kind(row["kind"]),
        payload=payload if isinstance(payload, dict) else {},
        route=route,
    )


class MomConsumer:
    def __init__(
        self, pool: asyncpg.Pool, group_name: str, consumer_id: str,
    ) -> None:
        self._pool = pool
        self._group_name = group_name
        self._consumer_id = consumer_id

    async def claim_batch(
        self,
        *,
        instance_id: str | None = None,
        direction: Direction | None = None,
        batch_size: int = 50,
    ) -> list[Envelope]:
        dir_str = str(direction) if direction else None
        async with self._pool.acquire() as conn, conn.transaction():
            claimed_rows = await conn.fetch(
                _CLAIM_SQL,
                self._group_name, instance_id, dir_str,
                batch_size, self._consumer_id,
            )
            if not claimed_rows:
                return []
            msg_ids = [r["msg_id"] for r in claimed_rows]
            msg_rows = await conn.fetch(_FETCH_MSGS, msg_ids)
        return [_row_to_envelope(r) for r in msg_rows]

    async def ack(self, msg_id: str | UUID) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(_ACK_SQL, self._group_name, UUID(str(msg_id)))

    async def fail(self, msg_id: str | UUID, error: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                _FAIL_SQL, self._group_name, UUID(str(msg_id)),
                MAX_RETRIES, error,
            )

    async def reclaim_stale(
        self, max_idle: timedelta = timedelta(seconds=30),
    ) -> int:
        interval_str = f"{int(max_idle.total_seconds())} seconds"
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                _RECLAIM_SQL, interval_str, self._group_name,
            )
        count = int(result.split()[-1]) if result else 0
        if count > 0:
            _log.info("mom.reclaimed", group=self._group_name, count=count)
        return count
