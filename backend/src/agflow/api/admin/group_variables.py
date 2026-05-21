"""Admin API pour les variables globales de groupe.

Prefix : /api/admin/groups/{group_id}/variables
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from agflow.auth.dependencies import require_operator as require_admin
from agflow.schemas.group_variables import (
    GroupVariableCreate,
    GroupVariableRow,
    GroupVariableUpdate,
)
from agflow.services import group_variables_service

router = APIRouter(
    prefix="/api/admin/groups/{group_id}/variables",
    tags=["admin-groups"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[GroupVariableRow])
async def list_variables(group_id: UUID):
    return await group_variables_service.list_by_group(group_id)


@router.post("", response_model=GroupVariableRow, status_code=status.HTTP_201_CREATED)
async def create_variable(group_id: UUID, payload: GroupVariableCreate):
    try:
        return await group_variables_service.create(
            group_id=group_id,
            name=payload.name,
            value=payload.value,
            description=payload.description,
        )
    except group_variables_service.GroupVariableInvalidNameError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except group_variables_service.GroupVariableDuplicateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc


@router.put("/{var_id}", response_model=GroupVariableRow)
async def update_variable(group_id: UUID, var_id: UUID, payload: GroupVariableUpdate):
    try:
        return await group_variables_service.update(
            var_id, **payload.model_dump(exclude_unset=True),
        )
    except group_variables_service.GroupVariableNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except group_variables_service.GroupVariableInvalidNameError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except group_variables_service.GroupVariableDuplicateError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc


@router.delete("/{var_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_variable(group_id: UUID, var_id: UUID):
    try:
        await group_variables_service.delete(var_id)
    except group_variables_service.GroupVariableNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
