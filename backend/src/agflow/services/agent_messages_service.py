from __future__ import annotations

from typing import Any
from uuid import UUID

from agflow.db.pool import fetch_all

# TODO: register jsonb codec in db/pool.py so asyncpg returns dict directly
# for `payload` / `route` JSONB columns instead of a JSON string. This service
# currently returns the raw value from asyncpg; callers/response models may
# need to handle string normalization until the codec is registered.


def _serialize(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "msg_id": str(row["msg_id"]),
        "parent_msg_id": str(row["parent_msg_id"]) if row["parent_msg_id"] else None,
        "direction": row["direction"],
        "kind": row["kind"],
        "payload": row["payload"],
        "source": row["source"],
        "created_at": row["created_at"].isoformat(),
        "route": row["route"],
    }


async def list_for_instance(
    *,
    session_id: UUID,
    instance_id: UUID,
    kind: str | None = None,
    direction: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Return messages persisted in `agent_messages` for a given instance.

    Results are ordered by `created_at DESC`, capped at `limit`.
    Optional filters: `kind` (exact match), `direction` (`in` | `out`).
    """
    conditions = ["session_id = $1", "instance_id = $2"]
    params: list[Any] = [str(session_id), str(instance_id)]
    idx = 3
    if kind:
        conditions.append(f"kind = ${idx}")
        params.append(kind)
        idx += 1
    if direction:
        conditions.append(f"direction = ${idx}")
        params.append(direction)
        idx += 1
    where = " AND ".join(conditions)
    params.append(limit)

    query = (
        "SELECT msg_id, parent_msg_id, direction, kind, payload, source, "
        "created_at, route "
        f"FROM agent_messages WHERE {where} "
        f"ORDER BY created_at DESC LIMIT ${idx}"
    )
    rows = await fetch_all(query, *params)
    return [_serialize(r) for r in rows]


__all__ = ["list_for_instance"]
