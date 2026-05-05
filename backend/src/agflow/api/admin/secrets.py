from __future__ import annotations

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
    description="Returns all secrets with their metadata. Values are never returned in clear text; use /reveal to retrieve a decrypted value.",
)
async def list_secrets() -> list[SecretSummary]:
    return await secrets_service.list_all()


@router.post(
    "",
    response_model=SecretSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Create a secret",
    description="Stores a new encrypted secret. Returns 201 on success, 409 if the name already exists.",
)
async def create_secret(payload: SecretCreate) -> SecretSummary:
    try:
        return await secrets_service.create(name=payload.name, value=payload.value)
    except secrets_service.DuplicateSecretError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get(
    "/resolve-status",
    summary="Resolve secret status for a list of names",
    description="Accepts a comma-separated list of secret names and returns a mapping of each name to its status: missing, empty, or ok.",
)
async def resolve_status(
    var_names: str = Query(..., description="Comma-separated list of secret names"),
) -> dict[str, str]:
    names = [n.strip().upper() for n in var_names.split(",") if n.strip()]
    return await secrets_service.resolve_status(names)


@router.put(
    "/{name}",
    response_model=SecretSummary,
    summary="Update a secret",
    description="Updates the value of an existing secret. Returns the updated SecretSummary, or 404 if not found.",
)
async def update_secret(name: str, payload: SecretUpdate) -> SecretSummary:
    try:
        await secrets_service.update(name, value=payload.value)
        return SecretSummary(name=name)
    except secrets_service.SecretNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete(
    "/{name}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a secret",
    description="Permanently deletes the secret. Returns 204 on success, 404 if not found.",
)
async def delete_secret(name: str) -> None:
    try:
        await secrets_service.delete(name)
    except secrets_service.SecretNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get(
    "/{name}/reveal",
    response_model=SecretReveal,
    summary="Reveal a secret's decrypted value",
    description="Returns the decrypted value of the secret. Returns 404 if the secret does not exist.",
)
async def reveal_secret(name: str) -> SecretReveal:
    try:
        return await secrets_service.reveal(name)
    except secrets_service.SecretNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/{name}/test",
    response_model=SecretTestResult,
    summary="Test a secret (LLM key validation)",
    description="Reveals the secret's value and submits it to the LLM key tester. Returns 404 if the secret does not exist.",
)
async def test_secret(name: str) -> SecretTestResult:
    try:
        revealed = await secrets_service.reveal(name)
    except secrets_service.SecretNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return await check_key(var_name=revealed.name, value=revealed.value)
