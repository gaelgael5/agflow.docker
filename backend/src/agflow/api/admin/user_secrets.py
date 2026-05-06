from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from agflow.auth.dependencies import require_viewer
from agflow.schemas.user_secrets import UserSecretCreate, UserSecretReveal, UserSecretSummary, UserSecretUpdate
from agflow.services import user_secrets_service

router = APIRouter(
    prefix="/api/admin/user-secrets",
    tags=["admin-user-secrets"],
    dependencies=[Depends(require_viewer)],
)


@router.get("", response_model=list[UserSecretSummary])
async def list_secrets(email: str = Depends(require_viewer)) -> list[UserSecretSummary]:
    return await user_secrets_service.list_secrets(email)


@router.post("", response_model=UserSecretSummary, status_code=status.HTTP_201_CREATED)
async def create_secret(payload: UserSecretCreate, email: str = Depends(require_viewer)) -> UserSecretSummary:
    try:
        return await user_secrets_service.create_secret(email, payload.name, payload.value, payload.description)
    except user_secrets_service.DuplicateSecretError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/{name}/reveal", response_model=UserSecretReveal)
async def reveal_secret(name: str, email: str = Depends(require_viewer)) -> UserSecretReveal:
    try:
        return await user_secrets_service.reveal_secret(email, name)
    except user_secrets_service.SecretNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{name}", response_model=UserSecretSummary)
async def update_secret(name: str, payload: UserSecretUpdate, email: str = Depends(require_viewer)) -> UserSecretSummary:
    try:
        return await user_secrets_service.update_secret(email, name, payload.value)
    except user_secrets_service.SecretNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_secret(name: str, email: str = Depends(require_viewer)) -> None:
    try:
        await user_secrets_service.delete_secret(email, name)
    except user_secrets_service.SecretNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
