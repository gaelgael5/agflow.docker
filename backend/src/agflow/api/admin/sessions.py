from __future__ import annotations

import json
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from agflow.auth.dependencies import require_admin
from agflow.mom.envelope import Kind
from agflow.schemas.admin_sessions import AdminSessionListItem
from agflow.schemas.agent_messages import AgentMessageOut
from agflow.schemas.sessions import AgentInstanceOut, SessionOut
from agflow.services import (
    agent_messages_service,
    agents_instances_service,
    sessions_service,
)

router = APIRouter(prefix="/api/admin/sessions", tags=["admin-sessions"])

# Sentinel UUID passed to services that gate on `api_key_id` when we want the
# admin-scoped path (is_admin=True). The services ignore `api_key_id` in that
# branch so the value is inert.
_ADMIN_SENTINEL_KEY = UUID(int=0)


@router.get("", response_model=list[AdminSessionListItem])
async def admin_list_sessions(
    _admin: str = Depends(require_admin),
    project_id: str | None = Query(default=None),
) -> list[AdminSessionListItem]:
    rows = await sessions_service.list_all_with_counts()
    if project_id is not None:
        rows = [r for r in rows if r.get("project_id") == project_id]
    return [AdminSessionListItem(**r) for r in rows]


@router.get("/{session_id}", response_model=SessionOut)
async def admin_get_session(
    session_id: UUID,
    _admin: str = Depends(require_admin),
) -> SessionOut:
    row = await sessions_service.get(
        session_id=session_id,
        api_key_id=_ADMIN_SENTINEL_KEY,
        is_admin=True,
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    return SessionOut(**row)


@router.get("/{session_id}/agents", response_model=list[AgentInstanceOut])
async def admin_list_session_agents(
    session_id: UUID,
    _admin: str = Depends(require_admin),
) -> list[AgentInstanceOut]:
    session = await sessions_service.get(
        session_id=session_id,
        api_key_id=_ADMIN_SENTINEL_KEY,
        is_admin=True,
    )
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    rows = await agents_instances_service.list_for_session(session_id=session_id)
    # `labels` is stored as JSONB and returned by asyncpg as a JSON string
    # unless a codec is registered on the connection. Decode here so the
    # Pydantic model can validate a `dict[str, Any]`.
    # TODO: register jsonb codec in db/pool.py to remove this local normalization.
    normalized: list[dict[str, Any]] = []
    for r in rows:
        row = dict(r)
        labels = row.get("labels")
        if isinstance(labels, str):
            row["labels"] = json.loads(labels) if labels else {}
        normalized.append(row)
    return [AgentInstanceOut(**r) for r in normalized]


@router.get(
    "/{session_id}/agents/{instance_id}/messages",
    response_model=list[AgentMessageOut],
)
async def admin_list_agent_messages(
    session_id: UUID,
    instance_id: UUID,
    _admin: str = Depends(require_admin),
    kind: Annotated[Kind | None, Query()] = None,
    direction: Annotated[str | None, Query(pattern="^(in|out)$")] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> list[AgentMessageOut]:
    # Confirm session ownership / existence before exposing messages.
    session = await sessions_service.get(
        session_id=session_id,
        api_key_id=_ADMIN_SENTINEL_KEY,
        is_admin=True,
    )
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")

    rows = await agent_messages_service.list_for_instance(
        session_id=session_id,
        instance_id=instance_id,
        kind=kind.value if kind is not None else None,
        direction=direction,
        limit=limit,
    )
    return [AgentMessageOut(**r) for r in rows]


__all__ = ["router"]
