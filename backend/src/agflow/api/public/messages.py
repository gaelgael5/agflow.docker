from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel

from agflow.auth.api_key import require_api_key
from agflow.db.pool import fetch_all, get_pool
from agflow.mom.envelope import Direction, Kind, Route
from agflow.mom.publisher import MomPublisher

router = APIRouter(prefix="/api/v1", tags=["public-messages"])

_GROUPS_CONFIG = {
    Direction.IN: ["dispatcher"],
    Direction.OUT: ["ws_push", "router"],
}


class MessageIn(BaseModel):
    kind: Kind = Kind.INSTRUCTION
    payload: dict[str, Any]
    route_to: str | None = None


@router.post("/sessions/{session_id}/agents/{instance_id}/message")
async def post_message(
    session_id: str,
    instance_id: str,
    body: MessageIn,
    request: Request,
    _key: dict = require_api_key("messages:write"),  # noqa: B008
) -> dict[str, str]:
    pool = await get_pool()
    publisher = MomPublisher(pool=pool, groups_config=_GROUPS_CONFIG)

    source_id = getattr(request.state, "api_key_id", "anonymous")
    route = Route(target=body.route_to) if body.route_to else None

    msg_id = await publisher.publish(
        session_id=session_id,
        instance_id=instance_id,
        direction=Direction.IN,
        source=f"api_key:{source_id}",
        kind=body.kind,
        payload=body.payload,
        route=route,
    )
    return {"msg_id": str(msg_id)}


@router.get("/sessions/{session_id}/agents/{instance_id}/messages")
async def get_messages(
    session_id: str,
    instance_id: str,
    kind: str | None = None,
    direction: str | None = None,
    limit: int = 100,
    _key: dict = require_api_key("messages:read"),  # noqa: B008
) -> list[dict[str, Any]]:
    conditions = ["session_id = $1", "instance_id = $2"]
    params: list[Any] = [session_id, instance_id]
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
        f"SELECT msg_id, parent_msg_id, direction, kind, payload, source, "
        f"created_at, route "
        f"FROM agent_messages WHERE {where} "
        f"ORDER BY created_at DESC LIMIT ${idx}"
    )
    rows = await fetch_all(query, *params)
    return [
        {
            "msg_id": str(r["msg_id"]),
            "parent_msg_id": str(r["parent_msg_id"]) if r["parent_msg_id"] else None,
            "direction": r["direction"],
            "kind": r["kind"],
            "payload": r["payload"],
            "source": r["source"],
            "created_at": r["created_at"].isoformat(),
            "route": r["route"],
        }
        for r in rows
    ]
