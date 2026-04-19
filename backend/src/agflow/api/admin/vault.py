from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from agflow.auth.dependencies import require_admin
from agflow.schemas.user_secrets import VaultChangePassphrase, VaultSetup, VaultStatus
from agflow.services import user_secrets_service, users_service

router = APIRouter(
    prefix="/api/admin/vault",
    tags=["admin-vault"],
    dependencies=[Depends(require_admin)],
)


async def _get_user_id(admin_email: str = Depends(require_admin)) -> object:
    user = await users_service.get_by_email(admin_email)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user.id


@router.get(
    "/status",
    response_model=VaultStatus,
    summary="Get vault initialization status",
    description="Returns whether the authenticated user's vault has been initialized and contains the PBKDF2 salt and verification ciphertext needed for client-side decryption.",
)
async def vault_status(user_id: object = Depends(_get_user_id)) -> VaultStatus:
    return await user_secrets_service.get_vault_status(user_id)


@router.post(
    "/setup",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Initialize the user vault",
    description="Stores the PBKDF2 salt and a verification ciphertext to bootstrap the client-side encrypted vault. Returns 409 if the vault is already initialized.",
)
async def vault_setup(payload: VaultSetup, user_id: object = Depends(_get_user_id)) -> None:
    try:
        await user_secrets_service.setup_vault(
            user_id, payload.salt, payload.test_ciphertext, payload.test_iv
        )
    except user_secrets_service.VaultAlreadyInitializedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post(
    "/change-passphrase",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Change vault passphrase",
    description="Updates the vault salt and re-saves all secrets re-encrypted with the new passphrase in a single atomic operation. Returns 409 if the vault has not been initialized yet.",
)
async def vault_change_passphrase(
    payload: VaultChangePassphrase, user_id: object = Depends(_get_user_id)
) -> None:
    try:
        re_encrypted = [
            {"id": s.id, "ciphertext": s.ciphertext, "iv": s.iv}
            for s in payload.re_encrypted_secrets
        ]
        await user_secrets_service.change_vault_passphrase(
            user_id, payload.salt, payload.test_ciphertext, payload.test_iv, re_encrypted
        )
    except user_secrets_service.VaultNotInitializedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
