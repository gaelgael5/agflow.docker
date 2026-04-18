from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from agflow.auth.dependencies import require_admin
from agflow.schemas.user_secrets import UserSecretCreate, UserSecretSummary, UserSecretUpdate
from agflow.services import user_secrets_service, users_service

router = APIRouter(
    prefix="/api/admin/user-secrets",
    tags=["admin-user-secrets"],
    dependencies=[Depends(require_admin)],
)


async def _get_user_id(admin_email: str = Depends(require_admin)) -> object:
    user = await users_service.get_by_email(admin_email)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user.id


@router.get(
    "",
    response_model=list[UserSecretSummary],
    summary="List current user's secrets",
    description="Returns all encrypted secrets belonging to the authenticated admin user. Ciphertext and IV are included but the plaintext is never stored server-side.",
)
async def list_secrets(user_id: object = Depends(_get_user_id)) -> list[UserSecretSummary]:
    return await user_secrets_service.list_secrets(user_id)


@router.post(
    "",
    response_model=UserSecretSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Store a new encrypted secret",
    description="Persists a client-encrypted secret (ciphertext + IV) for the authenticated user. Returns 409 if a secret with the same name already exists.",
)
async def create_secret(
    payload: UserSecretCreate, user_id: object = Depends(_get_user_id)
) -> UserSecretSummary:
    try:
        return await user_secrets_service.create_secret(
            user_id, payload.name, payload.ciphertext, payload.iv
        )
    except user_secrets_service.DuplicateSecretError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.put(
    "/{secret_id}",
    response_model=UserSecretSummary,
    summary="Replace an encrypted secret's value",
    description="Replaces the ciphertext and IV of an existing secret owned by the authenticated user. Returns 404 if the secret does not exist or does not belong to the user.",
)
async def update_secret(
    secret_id: UUID, payload: UserSecretUpdate, user_id: object = Depends(_get_user_id)
) -> UserSecretSummary:
    try:
        return await user_secrets_service.update_secret(
            secret_id, user_id, payload.ciphertext, payload.iv
        )
    except user_secrets_service.SecretNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete(
    "/{secret_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a secret",
    description="Permanently removes the secret identified by its UUID from the authenticated user's vault. Returns 404 if the secret is not found or belongs to another user.",
)
async def delete_secret(
    secret_id: UUID, user_id: object = Depends(_get_user_id)
) -> None:
    try:
        await user_secrets_service.delete_secret(secret_id, user_id)
    except user_secrets_service.SecretNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
