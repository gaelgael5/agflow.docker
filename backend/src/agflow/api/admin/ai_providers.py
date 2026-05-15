from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from agflow.auth.dependencies import require_operator as require_admin
from agflow.schemas.ai_providers import ProviderConfig, ProviderConfigUpdate, ProviderSummary
from agflow.schemas.secrets import SecretTestResult
from agflow.services import ai_providers_service
from agflow.services import llm_key_tester

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


@router.post("/{service_type}/{provider_name}/test", response_model=SecretTestResult)
async def test_provider(service_type: str, provider_name: str):
    try:
        api_key = await ai_providers_service.resolve_api_key(service_type, provider_name)
    except Exception as exc:
        return SecretTestResult(supported=False, ok=False, detail=f"Secret resolution failed: {exc}")

    providers = ai_providers_service.list_all()
    provider = next(
        (p for p in providers if p.service_type == service_type and p.provider_name == provider_name),
        None,
    )
    if provider is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not found")

    if not api_key:
        return SecretTestResult(supported=True, ok=False, detail=f"Secret '{provider.secret_ref}' is empty or not configured")

    return await llm_key_tester.check_key(provider.secret_ref, api_key)
