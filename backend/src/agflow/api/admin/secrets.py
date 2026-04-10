from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from agflow.auth.dependencies import require_admin
from agflow.schemas.secrets import (
    SecretCreate,
    SecretReveal,
    SecretSummary,
    SecretTestResult,
    SecretUpdate,
)
from agflow.services import secrets_service
from agflow.services.llm_key_tester import check_key

router = APIRouter(
    prefix="/api/admin/secrets",
    tags=["admin-secrets"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[SecretSummary])
async def list_secrets() -> list[SecretSummary]:
    return await secrets_service.list_all()


@router.post("", response_model=SecretSummary, status_code=status.HTTP_201_CREATED)
async def create_secret(payload: SecretCreate) -> SecretSummary:
    try:
        return await secrets_service.create(
            var_name=payload.var_name,
            value=payload.value,
            scope=payload.scope,
        )
    except secrets_service.DuplicateSecretError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc


@router.get("/resolve-status")
async def resolve_status(
    var_names: str = Query(..., description="Comma-separated list of var names"),
) -> dict[str, str]:
    names = [n.strip().upper() for n in var_names.split(",") if n.strip()]
    return await secrets_service.resolve_status(names)


@router.put("/{secret_id}", response_model=SecretSummary)
async def update_secret(secret_id: UUID, payload: SecretUpdate) -> SecretSummary:
    try:
        return await secrets_service.update(
            secret_id, value=payload.value, scope=payload.scope
        )
    except secrets_service.SecretNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.delete("/{secret_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_secret(secret_id: UUID) -> None:
    try:
        await secrets_service.delete(secret_id)
    except secrets_service.SecretNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.get("/{secret_id}/reveal", response_model=SecretReveal)
async def reveal_secret(secret_id: UUID) -> SecretReveal:
    try:
        return await secrets_service.reveal(secret_id)
    except secrets_service.SecretNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.post("/{secret_id}/test", response_model=SecretTestResult)
async def test_secret(secret_id: UUID) -> SecretTestResult:
    try:
        revealed = await secrets_service.reveal(secret_id)
    except secrets_service.SecretNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return await check_key(var_name=revealed.var_name, value=revealed.value)
