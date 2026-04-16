from __future__ import annotations

from uuid import UUID

import asyncpg
import structlog
from fastapi import APIRouter, HTTPException, status

from agflow.auth.api_key import require_api_key
from agflow.auth.context import AuthContext
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
