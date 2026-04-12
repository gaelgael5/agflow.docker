from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from agflow.auth.dependencies import require_admin
from agflow.schemas.api_keys import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeySummary,
    ApiKeyUpdate,
)
from agflow.services import api_keys_service

router = APIRouter(
    prefix="/api/admin/api-keys",
    tags=["admin-api-keys"],
    dependencies=[Depends(require_admin)],
)


@router.post("", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_api_key(payload: ApiKeyCreate) -> ApiKeyCreated:
    # Admin creates keys — all scopes are allowed; no user scope validation needed.
    # When a real user context is available, validate_key_scopes will be called here.
    expires_at = api_keys_service.compute_expiry(payload.expires_in)
    # owner_id is nil UUID for admin-created system keys (no user associated yet)
    nil_owner = UUID("00000000-0000-0000-0000-000000000000")
    return await api_keys_service.create(
        name=payload.name,
        scopes=payload.scopes,
        rate_limit=payload.rate_limit,
        expires_at=expires_at,
        owner_id=nil_owner,
    )


@router.get("", response_model=list[ApiKeySummary])
async def list_api_keys() -> list[ApiKeySummary]:
    return await api_keys_service.list_all()


@router.get("/{key_id}", response_model=ApiKeySummary)
async def get_api_key(key_id: UUID) -> ApiKeySummary:
    try:
        return await api_keys_service.get_by_id(key_id)
    except api_keys_service.ApiKeyNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.patch("/{key_id}", response_model=ApiKeySummary)
async def update_api_key(key_id: UUID, payload: ApiKeyUpdate) -> ApiKeySummary:
    try:
        return await api_keys_service.update(
            key_id,
            **payload.model_dump(exclude_unset=True),
        )
    except api_keys_service.ApiKeyNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(key_id: UUID) -> None:
    try:
        await api_keys_service.revoke(key_id)
    except api_keys_service.ApiKeyNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
