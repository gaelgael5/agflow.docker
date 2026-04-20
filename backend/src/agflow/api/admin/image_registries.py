from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from agflow.auth.dependencies import require_operator as require_admin
from agflow.schemas.products import (
    RegistryCreate,
    RegistrySummary,
    RegistryUpdate,
)
from agflow.services import image_registries_service

router = APIRouter(
    prefix="/api/admin/image-registries",
    tags=["admin-registries"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[RegistrySummary])
async def list_registries():
    return image_registries_service.list_all()


@router.post("", response_model=RegistrySummary, status_code=status.HTTP_201_CREATED)
async def create_registry(payload: RegistryCreate):
    try:
        return image_registries_service.create(
            registry_id=payload.id,
            display_name=payload.display_name,
            url=payload.url,
            auth_type=payload.auth_type,
            credential_ref=payload.credential_ref,
        )
    except image_registries_service.DuplicateRegistryError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/{registry_id}", response_model=RegistrySummary)
async def get_registry(registry_id: str):
    try:
        return image_registries_service.get_by_id(registry_id)
    except image_registries_service.RegistryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{registry_id}", response_model=RegistrySummary)
async def update_registry(registry_id: str, payload: RegistryUpdate):
    try:
        return image_registries_service.update(registry_id, **payload.model_dump(exclude_unset=True))
    except image_registries_service.RegistryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{registry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_registry(registry_id: str):
    try:
        image_registries_service.delete(registry_id)
    except image_registries_service.RegistryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
