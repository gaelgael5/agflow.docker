from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from agflow.auth.dependencies import require_admin
from agflow.schemas.platform_secrets import (
    PlatformSecretCreateEnv,
    PlatformSecretCreateVault,
    PlatformSecretReveal,
    PlatformSecretSummary,
    PlatformSecretUpdate,
)
from agflow.services import platform_secrets_service, vault_client
from agflow.services.platform_secrets_service import (
    DuplicatePlatformSecretError,
    PlatformSecretNotFoundError,
)

router = APIRouter(
    prefix="/api/admin/secrets",
    tags=["admin-secrets"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[PlatformSecretSummary])
async def list_secrets() -> list[PlatformSecretSummary]:
    return await platform_secrets_service.list_all()


@router.post("/vault", response_model=PlatformSecretSummary, status_code=status.HTTP_201_CREATED)
async def create_vault_secret(payload: PlatformSecretCreateVault) -> PlatformSecretSummary:
    try:
        return await platform_secrets_service.create_vault(payload.name, payload.value)
    except DuplicatePlatformSecretError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except vault_client.VaultNotFoundError as exc:
        # Aucun coffre Harpocrate configuré : l'UI doit guider vers /settings.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc),
        ) from exc


@router.post("/env", response_model=PlatformSecretSummary, status_code=status.HTTP_201_CREATED)
async def create_env_secret(payload: PlatformSecretCreateEnv) -> PlatformSecretSummary:
    try:
        return await platform_secrets_service.create_env(payload.name, payload.value)
    except DuplicatePlatformSecretError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/resolve-status")
async def resolve_status(
    var_names: str = Query(..., description="Comma-separated list of variable names"),
) -> dict[str, str]:
    names = [n.strip().upper() for n in var_names.split(",") if n.strip()]
    all_secrets = await platform_secrets_service.resolve_all()
    result: dict[str, str] = {}
    for name in names:
        if name not in all_secrets:
            result[name] = "missing"
        elif not all_secrets[name]:
            result[name] = "empty"
        else:
            result[name] = "ok"
    return result


@router.put("/{secret_id}", status_code=status.HTTP_204_NO_CONTENT)
async def update_secret(secret_id: UUID, payload: PlatformSecretUpdate) -> None:
    try:
        await platform_secrets_service.update(secret_id, payload.value)
    except PlatformSecretNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{secret_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_secret(secret_id: UUID) -> None:
    try:
        await platform_secrets_service.delete(secret_id)
    except PlatformSecretNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{secret_id}/reveal", response_model=PlatformSecretReveal)
async def reveal_secret(secret_id: UUID) -> PlatformSecretReveal:
    try:
        return await platform_secrets_service.reveal(secret_id)
    except PlatformSecretNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
