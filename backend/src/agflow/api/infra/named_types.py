from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from agflow.auth.dependencies import require_operator as require_admin
from agflow.schemas.infra import (
    NamedTypeCreate,
    NamedTypeRow,
    NamedTypeUpdate,
)
from agflow.services import infra_named_types_service

router = APIRouter(
    prefix="/api/infra/named-types",
    tags=["infra-named-types"],
)

_admin = [Depends(require_admin)]


@router.get("", response_model=list[NamedTypeRow], dependencies=_admin)
async def list_named_types():
    return await infra_named_types_service.list_all()


@router.post(
    "", response_model=NamedTypeRow, status_code=status.HTTP_201_CREATED, dependencies=_admin,
)
async def create_named_type(payload: NamedTypeCreate):
    return await infra_named_types_service.create(
        name=payload.name,
        type_id=payload.type_id,
        sub_type_id=payload.sub_type_id,
        connection_type=payload.connection_type,
    )


@router.get("/{named_type_id}", response_model=NamedTypeRow, dependencies=_admin)
async def get_named_type(named_type_id: UUID):
    try:
        return await infra_named_types_service.get_by_id(named_type_id)
    except infra_named_types_service.NamedTypeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{named_type_id}", response_model=NamedTypeRow, dependencies=_admin)
async def update_named_type(named_type_id: UUID, payload: NamedTypeUpdate):
    try:
        return await infra_named_types_service.update(
            named_type_id, **payload.model_dump(exclude_unset=True),
        )
    except infra_named_types_service.NamedTypeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{named_type_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=_admin)
async def delete_named_type(named_type_id: UUID):
    try:
        await infra_named_types_service.delete(named_type_id)
    except infra_named_types_service.NamedTypeNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
