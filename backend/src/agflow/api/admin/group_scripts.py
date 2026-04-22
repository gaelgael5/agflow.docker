from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from agflow.auth.dependencies import require_operator as require_admin
from agflow.schemas.scripts import (
    GroupScriptCreate,
    GroupScriptRow,
    GroupScriptUpdate,
)
from agflow.services import group_scripts_service

router = APIRouter(
    prefix="/api/admin/groups/{group_id}/scripts",
    tags=["admin-groups"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[GroupScriptRow])
async def list_group_scripts(group_id: UUID):
    return await group_scripts_service.list_by_group(group_id)


@router.post("", response_model=GroupScriptRow, status_code=status.HTTP_201_CREATED)
async def create_group_script(group_id: UUID, payload: GroupScriptCreate):
    return await group_scripts_service.create(
        group_id=group_id,
        script_id=payload.script_id,
        machine_id=payload.machine_id,
        timing=payload.timing,
        position=payload.position,
        env_mapping=payload.env_mapping,
    )


@router.put("/{link_id}", response_model=GroupScriptRow)
async def update_group_script(group_id: UUID, link_id: UUID, payload: GroupScriptUpdate):
    try:
        return await group_scripts_service.update(
            link_id, **payload.model_dump(exclude_unset=True),
        )
    except group_scripts_service.GroupScriptNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group_script(group_id: UUID, link_id: UUID):
    try:
        await group_scripts_service.delete(link_id)
    except group_scripts_service.GroupScriptNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
