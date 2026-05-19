"""Endpoints REST pour le paramétrage OIDC/Keycloak."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from agflow.auth.dependencies import require_admin
from agflow.schemas.auth_config import (
    AuthConfigOut,
    AuthConfigUpdate,
    AuthTestRequest,
    AuthTestResult,
)
from agflow.services import auth_config_service

router = APIRouter(
    prefix="/api/admin/auth-config",
    tags=["admin-auth-config"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=AuthConfigOut)
async def get_auth_config() -> AuthConfigOut:
    """Retourne la config OIDC (sans révéler le secret)."""
    return await auth_config_service.get_config()


@router.put("", response_model=AuthConfigOut)
async def update_auth_config(
    payload: AuthConfigUpdate, actor_user_id: str = Depends(require_admin)
) -> AuthConfigOut:
    """Met à jour la config. Le client_secret (si fourni en clair) est
    poussé dans Harpocrate et seul le ref est stocké en DB."""
    # require_admin retourne le `sub` claim (typiquement un email) — on tente la conversion UUID
    actor_uuid: UUID | None
    try:
        actor_uuid = UUID(actor_user_id) if actor_user_id else None
    except ValueError:
        actor_uuid = None

    try:
        return await auth_config_service.update_config(payload, actor_user_id=actor_uuid)
    except auth_config_service.InvalidUrlError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except auth_config_service.VaultNameUnknownError as exc:
        raise HTTPException(status_code=404, detail=f"vault not found: {exc}") from exc


@router.post("/test", response_model=AuthTestResult)
async def test_auth_config(payload: AuthTestRequest) -> AuthTestResult:
    """Teste la connexion Keycloak. Toujours HTTP 200 ; le succès/échec
    est dans `ok`."""
    return await auth_config_service.test_connection(payload)
