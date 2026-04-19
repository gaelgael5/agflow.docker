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


@router.get(
    "",
    response_model=list[SecretSummary],
    summary="List all secrets",
    description="Returns all secrets with their metadata (name, scope, env var name). Secret values are never returned in clear text; use the /reveal endpoint to retrieve a decrypted value.",
)
async def list_secrets() -> list[SecretSummary]:
    return await secrets_service.list_all()


@router.post(
    "",
    response_model=SecretSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Create a secret",
    description="Stores a new encrypted secret. Returns 201 with the SecretSummary on success, or 409 if a secret with the same var_name already exists.",
)
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


@router.get(
    "/resolve-status",
    summary="Resolve secret status for a list of var names",
    description="Accepts a comma-separated list of environment variable names and returns a mapping of each name to its status: missing, empty, or filled. Used to drive status indicators in the UI.",
)
async def resolve_status(
    var_names: str = Query(..., description="Comma-separated list of var names"),
) -> dict[str, str]:
    names = [n.strip().upper() for n in var_names.split(",") if n.strip()]
    return await secrets_service.resolve_status(names)


@router.put(
    "/{secret_id}",
    response_model=SecretSummary,
    summary="Update a secret",
    description="Updates the value and/or scope of an existing secret identified by its UUID. Returns the updated SecretSummary, or 404 if not found.",
)
async def update_secret(secret_id: UUID, payload: SecretUpdate) -> SecretSummary:
    try:
        return await secrets_service.update(
            secret_id, value=payload.value, scope=payload.scope
        )
    except secrets_service.SecretNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.delete(
    "/{secret_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a secret",
    description="Permanently deletes the secret identified by its UUID. Returns 204 on success, or 404 if the secret does not exist.",
)
async def delete_secret(secret_id: UUID) -> None:
    try:
        await secrets_service.delete(secret_id)
    except secrets_service.SecretNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.get(
    "/{secret_id}/reveal",
    response_model=SecretReveal,
    summary="Reveal a secret's decrypted value",
    description="Returns the decrypted value of the secret as a SecretReveal object. This is the only endpoint that exposes the clear-text value; it should be used sparingly. Returns 404 if the secret does not exist.",
)
async def reveal_secret(secret_id: UUID) -> SecretReveal:
    try:
        return await secrets_service.reveal(secret_id)
    except secrets_service.SecretNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.post(
    "/{secret_id}/test",
    response_model=SecretTestResult,
    summary="Test a secret (LLM key validation)",
    description="Reveals the secret's value and submits it to the LLM key tester. Returns a SecretTestResult indicating whether the key is valid for its associated provider. Returns 404 if the secret does not exist.",
)
async def test_secret(secret_id: UUID) -> SecretTestResult:
    try:
        revealed = await secrets_service.reveal(secret_id)
    except secrets_service.SecretNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    return await check_key(var_name=revealed.var_name, value=revealed.value)
