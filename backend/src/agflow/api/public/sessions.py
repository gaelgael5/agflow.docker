from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID

import asyncpg
import structlog
from fastapi import (
    APIRouter,
    HTTPException,
    WebSocket,
    WebSocketDisconnect,
    status,
)

from agflow.auth.api_key import require_api_key
from agflow.auth.context import AuthContext
from agflow.db.pool import fetch_all
from agflow.schemas.sessions import (
    AgentInstanceCreate,
    AgentInstanceCreated,
    AgentInstanceOut,
    SessionCreate,
    SessionExtend,
    SessionOut,
)
from agflow.services import (
    agents_instances_service,
    sessions_service,
)

_log = structlog.get_logger(__name__)

router = APIRouter()


@router.post("/api/v1/sessions", status_code=status.HTTP_201_CREATED)
async def create_session(
    body: SessionCreate, api_key: dict = require_api_key(),  # noqa: B008
) -> SessionOut:
    ctx = AuthContext.from_api_key(api_key)
    row = await sessions_service.create(
        api_key_id=ctx.api_key_id, name=body.name,
        duration_seconds=body.duration_seconds,
    )
    return SessionOut(**row)


@router.get("/api/v1/sessions/{session_id}")
async def get_session(
    session_id: UUID, api_key: dict = require_api_key(),  # noqa: B008
) -> SessionOut:
    ctx = AuthContext.from_api_key(api_key)
    row = await sessions_service.get(
        session_id=session_id, api_key_id=ctx.api_key_id, is_admin=ctx.is_admin,
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    return SessionOut(**row)


@router.patch("/api/v1/sessions/{session_id}/extend")
async def extend_session(
    session_id: UUID, body: SessionExtend,
    api_key: dict = require_api_key(),  # noqa: B008
) -> SessionOut:
    ctx = AuthContext.from_api_key(api_key)
    row = await sessions_service.extend(
        session_id=session_id, api_key_id=ctx.api_key_id, is_admin=ctx.is_admin,
        additional_seconds=body.duration_seconds,
    )
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "session not found or not active",
        )
    return SessionOut(**row)


@router.delete(
    "/api/v1/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def close_session(
    session_id: UUID, api_key: dict = require_api_key(),  # noqa: B008
) -> None:
    ctx = AuthContext.from_api_key(api_key)
    ok = await sessions_service.close(
        session_id=session_id, api_key_id=ctx.api_key_id, is_admin=ctx.is_admin,
    )
    if not ok:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "session not found or already closed",
        )


@router.post(
    "/api/v1/sessions/{session_id}/agents",
    status_code=status.HTTP_201_CREATED,
)
async def create_agents(
    session_id: UUID, body: AgentInstanceCreate,
    api_key: dict = require_api_key(),  # noqa: B008
) -> AgentInstanceCreated:
    ctx = AuthContext.from_api_key(api_key)
    session = await sessions_service.get(
        session_id=session_id, api_key_id=ctx.api_key_id, is_admin=ctx.is_admin,
    )
    if session is None or session["status"] != "active":
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "session not found or not active",
        )

    try:
        ids = await agents_instances_service.create(
            session_id=session_id,
            agent_id=body.agent_id,
            count=body.count,
            labels=body.labels,
            mission=body.mission,
        )
    except asyncpg.ForeignKeyViolationError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"agent_id '{body.agent_id}' not found in catalog",
        ) from exc
    return AgentInstanceCreated(instance_ids=ids)


@router.get("/api/v1/sessions/{session_id}/agents")
async def list_agents(
    session_id: UUID, api_key: dict = require_api_key(),  # noqa: B008
) -> list[AgentInstanceOut]:
    ctx = AuthContext.from_api_key(api_key)
    session = await sessions_service.get(
        session_id=session_id, api_key_id=ctx.api_key_id, is_admin=ctx.is_admin,
    )
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    rows = await agents_instances_service.list_for_session(session_id=session_id)
    return [AgentInstanceOut(**r) for r in rows]


@router.delete(
    "/api/v1/sessions/{session_id}/agents/{instance_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def destroy_agent(
    session_id: UUID, instance_id: UUID,
    api_key: dict = require_api_key(),  # noqa: B008
) -> None:
    ctx = AuthContext.from_api_key(api_key)
    session = await sessions_service.get(
        session_id=session_id, api_key_id=ctx.api_key_id, is_admin=ctx.is_admin,
    )
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    ok = await agents_instances_service.destroy(
        session_id=session_id, instance_id=instance_id,
    )
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "instance not found")


@router.get("/api/v1/sessions/{session_id}/messages")
async def get_session_messages(
    session_id: UUID,
    kind: str | None = None,
    direction: str | None = None,
    limit: int = 200,
    api_key: dict = require_api_key(),  # noqa: B008
) -> list[dict[str, Any]]:
    ctx = AuthContext.from_api_key(api_key)
    session = await sessions_service.get(
        session_id=session_id, api_key_id=ctx.api_key_id, is_admin=ctx.is_admin,
    )
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")

    conditions = ["session_id = $1"]
    params: list[Any] = [str(session_id)]
    idx = 2
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
        "created_at, route, instance_id "
        f"FROM agent_messages WHERE {where} "
        f"ORDER BY created_at DESC LIMIT ${idx}"
    )
    rows = await fetch_all(query, *params)
    return [
        {
            "msg_id": str(r["msg_id"]),
            "parent_msg_id": str(r["parent_msg_id"]) if r["parent_msg_id"] else None,
            "instance_id": r["instance_id"],
            "direction": r["direction"],
            "kind": r["kind"],
            "payload": r["payload"],
            "source": r["source"],
            "created_at": r["created_at"].isoformat(),
            "route": r["route"],
        }
        for r in rows
    ]


@router.websocket("/api/v1/sessions/{session_id}/stream")
async def ws_session_stream(websocket: WebSocket, session_id: UUID) -> None:
    await websocket.accept()

    async def poll() -> None:
        last_seen_at = None
        while True:
            if last_seen_at is None:
                rows = await fetch_all(
                    "SELECT msg_id, parent_msg_id, instance_id, direction, kind, "
                    "payload, source, created_at, route "
                    "FROM agent_messages "
                    "WHERE session_id = $1 AND direction = 'out' "
                    "ORDER BY created_at DESC LIMIT 1",
                    str(session_id),
                )
                last_seen_at = rows[0]["created_at"] if rows else None
            rows = await fetch_all(
                "SELECT msg_id, parent_msg_id, instance_id, direction, kind, "
                "payload, source, created_at, route "
                "FROM agent_messages "
                "WHERE session_id = $1 AND direction = 'out' "
                "  AND ($2::timestamptz IS NULL OR created_at > $2) "
                "ORDER BY created_at",
                str(session_id), last_seen_at,
            )
            for r in rows:
                await websocket.send_json({
                    "msg_id": str(r["msg_id"]),
                    "parent_msg_id": str(r["parent_msg_id"]) if r["parent_msg_id"] else None,
                    "instance_id": r["instance_id"],
                    "direction": r["direction"],
                    "kind": r["kind"],
                    "payload": r["payload"],
                    "source": r["source"],
                    "created_at": r["created_at"].isoformat(),
                    "route": r["route"],
                })
                last_seen_at = r["created_at"]
            if not rows:
                await asyncio.sleep(0.2)

    try:
        await poll()
    except WebSocketDisconnect:
        pass
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        _log.exception("ws_session_stream.error", error=str(exc))
