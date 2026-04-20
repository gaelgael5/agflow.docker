from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from agflow.auth.dependencies import require_operator as require_admin
from agflow.schemas.ai_providers import ProviderConfig, ProviderConfigUpdate, ProviderSummary
from agflow.services import ai_providers_service

router = APIRouter(
    prefix="/api/admin/ai-providers",
    tags=["admin-ai-providers"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[ProviderSummary])
async def list_providers(service_type: str | None = None):
    if service_type:
        return ai_providers_service.list_by_type(service_type)
    return ai_providers_service.list_all()


@router.post("", response_model=ProviderSummary, status_code=status.HTTP_201_CREATED)
async def create_provider(payload: ProviderConfig):
    try:
        return ai_providers_service.create(
            service_type=payload.service_type,
            provider_name=payload.provider_name,
            display_name=payload.display_name,
            secret_ref=payload.secret_ref,
            enabled=payload.enabled,
            is_default=payload.is_default,
        )
    except ai_providers_service.DuplicateProviderError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.put("/{service_type}/{provider_name}", response_model=ProviderSummary)
async def update_provider(service_type: str, provider_name: str, payload: ProviderConfigUpdate):
    try:
        return ai_providers_service.update(
            service_type, provider_name, **payload.model_dump(exclude_unset=True),
        )
    except ai_providers_service.ProviderNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{service_type}/{provider_name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider(service_type: str, provider_name: str):
    try:
        ai_providers_service.delete(service_type, provider_name)
    except ai_providers_service.ProviderNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
