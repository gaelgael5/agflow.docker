from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from agflow.auth.dependencies import require_operator as require_admin
from agflow.schemas.infra import (
    NamedTypeActionCreate,
    NamedTypeActionRow,
    NamedTypeActionUpdate,
)
from agflow.services import infra_named_type_actions_service

router = APIRouter(
    prefix="/api/infra/named-types/{named_type_id}/actions",
    tags=["infra-named-type-actions"],
)

_admin = [Depends(require_admin)]


@router.get("", response_model=list[NamedTypeActionRow], dependencies=_admin)
async def list_actions(named_type_id: UUID):
    return await infra_named_type_actions_service.list_by_named_type(named_type_id)


@router.post(
    "",
    response_model=NamedTypeActionRow,
    status_code=status.HTTP_201_CREATED,
    dependencies=_admin,
)
async def create_action(named_type_id: UUID, payload: NamedTypeActionCreate):
    return await infra_named_type_actions_service.create(
        named_type_id=named_type_id,
        category_action_id=payload.category_action_id,
        url=payload.url,
    )


@router.put("/{action_id}", response_model=NamedTypeActionRow, dependencies=_admin)
async def update_action(named_type_id: UUID, action_id: UUID, payload: NamedTypeActionUpdate):
    if payload.url is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="url is required")
    try:
        return await infra_named_type_actions_service.update(action_id, url=payload.url)
    except infra_named_type_actions_service.NamedTypeActionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{action_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=_admin)
async def delete_action(named_type_id: UUID, action_id: UUID):
    try:
        await infra_named_type_actions_service.delete(action_id)
    except infra_named_type_actions_service.NamedTypeActionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
