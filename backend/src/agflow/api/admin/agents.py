from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from agflow.auth.dependencies import require_admin
from agflow.schemas.agents import (
    AgentCreate,
    AgentDetail,
    AgentSummary,
    AgentUpdate,
    ConfigPreview,
    DuplicatePayload,
)
from agflow.services import agents_service, composition_builder

router = APIRouter(
    prefix="/api/admin/agents",
    tags=["admin-agents"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[AgentSummary])
async def list_agents() -> list[AgentSummary]:
    return await agents_service.list_all()


@router.post("", response_model=AgentDetail, status_code=status.HTTP_201_CREATED)
async def create_agent(payload: AgentCreate) -> AgentDetail:
    try:
        return await agents_service.create(payload)
    except agents_service.DuplicateAgentError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    except agents_service.InvalidReferenceError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.get("/{agent_id}", response_model=AgentDetail)
async def get_agent(agent_id: UUID) -> AgentDetail:
    try:
        return await agents_service.get_by_id(agent_id)
    except agents_service.AgentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.put("/{agent_id}", response_model=AgentDetail)
async def update_agent(agent_id: UUID, payload: AgentUpdate) -> AgentDetail:
    try:
        return await agents_service.update(agent_id, payload)
    except agents_service.AgentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except agents_service.InvalidReferenceError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(agent_id: UUID) -> None:
    try:
        await agents_service.delete(agent_id)
    except agents_service.AgentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.post(
    "/{agent_id}/duplicate",
    response_model=AgentDetail,
    status_code=status.HTTP_201_CREATED,
)
async def duplicate_agent(
    agent_id: UUID, payload: DuplicatePayload
) -> AgentDetail:
    try:
        return await agents_service.duplicate(
            agent_id, new_slug=payload.slug, new_display_name=payload.display_name
        )
    except agents_service.AgentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except agents_service.DuplicateAgentError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc


@router.get("/{agent_id}/config-preview", response_model=ConfigPreview)
async def preview_agent_config(agent_id: UUID) -> ConfigPreview:
    try:
        return await composition_builder.build_preview(agent_id)
    except agents_service.AgentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
