"""Router admin pour les coffres Harpocrate configurables côté DB.

Routes :
- GET    /api/admin/harpocrate-vaults
- POST   /api/admin/harpocrate-vaults
- PUT    /api/admin/harpocrate-vaults/{id}
- DELETE /api/admin/harpocrate-vaults/{id}
- POST   /api/admin/harpocrate-vaults/{id}/set-default
- POST   /api/admin/harpocrate-vaults/{id}/test-connection

La clé API n'apparaît jamais dans les réponses. `VaultSummary` exclut
`api_key`. La seule façon de la lire est `reveal_api_key()` côté service,
internal-only, utilisé par `vault_client`.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from agflow.auth.dependencies import require_operator as require_admin
from agflow.schemas.harpocrate_vaults import (
    VaultCreateRequest,
    VaultSummary,
    VaultTestConnectionResult,
    VaultUpdateRequest,
)
from agflow.services import harpocrate_vaults_service as vaults

router = APIRouter(
    prefix="/api/admin/harpocrate-vaults",
    tags=["admin-harpocrate-vaults"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[VaultSummary])
async def list_vaults() -> list[VaultSummary]:
    return await vaults.list_all()


@router.post("", response_model=VaultSummary, status_code=status.HTTP_201_CREATED)
async def create_vault(payload: VaultCreateRequest) -> VaultSummary:
    try:
        return await vaults.create(payload)
    except vaults.DuplicateVaultNameError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except vaults.NoDekConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc),
        ) from exc


@router.put("/{vault_id}", response_model=VaultSummary)
async def update_vault(vault_id: UUID, payload: VaultUpdateRequest) -> VaultSummary:
    try:
        return await vaults.update(vault_id, payload)
    except vaults.VaultNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except vaults.DuplicateVaultNameError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except vaults.NoDekConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc),
        ) from exc


@router.delete("/{vault_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vault(vault_id: UUID) -> None:
    try:
        await vaults.delete(vault_id)
    except vaults.VaultNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{vault_id}/set-default", response_model=VaultSummary)
async def set_default(vault_id: UUID) -> VaultSummary:
    try:
        return await vaults.set_default(vault_id)
    except vaults.VaultNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{vault_id}/test-connection", response_model=VaultTestConnectionResult)
async def test_connection(vault_id: UUID) -> VaultTestConnectionResult:
    try:
        return await vaults.test_connection(vault_id)
    except vaults.VaultNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
