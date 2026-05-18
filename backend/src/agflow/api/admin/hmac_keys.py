"""Endpoint POST /api/admin/hmac-keys (gestion des clés HMAC du callback workflow)."""
from __future__ import annotations

from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, status

from agflow.auth.dependencies import require_operator_or_m2m
from agflow.schemas.workflow import HmacKeyCreateRequest, HmacKeyCreateResponse
from agflow.services import hmac_keys_service

_log = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/admin/hmac-keys",
    tags=["admin-workflow"],
    dependencies=[Depends(require_operator_or_m2m)],
)


@router.post(
    "",
    response_model=HmacKeyCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def post_hmac_key(payload: HmacKeyCreateRequest) -> HmacKeyCreateResponse:
    try:
        await hmac_keys_service.create(
            key_id=payload.key_id,
            secret_hex=payload.secret_hex,
            description=payload.description,
        )
    except hmac_keys_service.DuplicateHmacKeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "key_id_already_exists", "message": str(exc)},
        ) from exc

    return HmacKeyCreateResponse(
        key_id=payload.key_id,
        description=payload.description,
        created_at=datetime.now(UTC).isoformat(),
    )


@router.delete(
    "/{key_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_hmac_key(key_id: str) -> None:
    """Soft-delete : marque la clé comme rotated (préserve l'historique).

    Idempotent : 204 même si déjà rotated.
    404 uniquement si la clé n'existe pas du tout.
    """
    try:
        await hmac_keys_service.mark_rotated(key_id=key_id)
    except hmac_keys_service.HmacKeyNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": "hmac_key_not_found", "message": str(exc)},
        ) from exc
