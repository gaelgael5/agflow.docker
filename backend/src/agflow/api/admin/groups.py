from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from agflow.auth.dependencies import require_operator as require_admin
from agflow.schemas.products import GroupCreate, GroupSummary, GroupUpdate
from agflow.services import groups_service

router = APIRouter(
    prefix="/api/admin/groups",
    tags=["admin-groups"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[GroupSummary])
async def list_groups(project_id: UUID):
    return await groups_service.list_by_project(project_id)


@router.post("", response_model=GroupSummary, status_code=status.HTTP_201_CREATED)
async def create_group(payload: GroupCreate):
    return await groups_service.create(
        project_id=payload.project_id,
        name=payload.name,
        max_agents=payload.max_agents,
    )


@router.get("/{group_id}", response_model=GroupSummary)
async def get_group(group_id: UUID):
    try:
        return await groups_service.get_by_id(group_id)
    except groups_service.GroupNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{group_id}", response_model=GroupSummary)
async def update_group(group_id: UUID, payload: GroupUpdate):
    try:
        return await groups_service.update(group_id, **payload.model_dump(exclude_unset=True))
    except groups_service.GroupNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(group_id: UUID):
    try:
        await groups_service.delete(group_id)
    except groups_service.GroupNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
