from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from agflow.auth.dependencies import require_admin
from agflow.schemas.agents import (
    AgentCreate,
    AgentDetail,
    AgentProfileCreate,
    AgentProfileSummary,
    AgentProfileUpdate,
    AgentSummary,
    AgentUpdate,
    ConfigPreview,
    DuplicatePayload,
)
from agflow.services import (
    agent_profiles_service,
    agents_service,
    composition_builder,
)

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
async def preview_agent_config(
    agent_id: UUID,
    profile_id: UUID | None = Query(
        default=None,
        description="Optional mission profile to apply. Without it, the "
        "prompt is identity-only.",
    ),
) -> ConfigPreview:
    try:
        return await composition_builder.build_preview(agent_id, profile_id)
    except agents_service.AgentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except agent_profiles_service.ProfileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ValueError as exc:
        # Profile belongs to a different agent
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


# ──────────────────────────────────────────────────────────────────
# Mission profiles (NF-3)
# ──────────────────────────────────────────────────────────────────


@router.get(
    "/{agent_id}/profiles", response_model=list[AgentProfileSummary]
)
async def list_profiles(agent_id: UUID) -> list[AgentProfileSummary]:
    try:
        await agents_service.get_by_id(agent_id)
    except agents_service.AgentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return await agent_profiles_service.list_for_agent(agent_id)


@router.post(
    "/{agent_id}/profiles",
    response_model=AgentProfileSummary,
    status_code=status.HTTP_201_CREATED,
)
async def create_profile(
    agent_id: UUID, payload: AgentProfileCreate
) -> AgentProfileSummary:
    try:
        await agents_service.get_by_id(agent_id)
    except agents_service.AgentNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    try:
        return await agent_profiles_service.create(
            agent_id=agent_id,
            name=payload.name,
            description=payload.description,
            document_ids=payload.document_ids,
        )
    except agent_profiles_service.DuplicateProfileError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc


@router.put(
    "/{agent_id}/profiles/{profile_id}",
    response_model=AgentProfileSummary,
)
async def update_profile(
    agent_id: UUID, profile_id: UUID, payload: AgentProfileUpdate
) -> AgentProfileSummary:
    try:
        existing = await agent_profiles_service.get_by_id(profile_id)
    except agent_profiles_service.ProfileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    if existing.agent_id != agent_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Profile {profile_id} does not belong to agent {agent_id}",
        )
    try:
        return await agent_profiles_service.update(
            profile_id,
            name=payload.name,
            description=payload.description,
            document_ids=payload.document_ids,
        )
    except agent_profiles_service.DuplicateProfileError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc


@router.delete(
    "/{agent_id}/profiles/{profile_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_profile(agent_id: UUID, profile_id: UUID) -> None:
    try:
        existing = await agent_profiles_service.get_by_id(profile_id)
    except agent_profiles_service.ProfileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    if existing.agent_id != agent_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Profile {profile_id} does not belong to agent {agent_id}",
        )
    await agent_profiles_service.delete(profile_id)
