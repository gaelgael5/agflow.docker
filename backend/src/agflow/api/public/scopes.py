from __future__ import annotations

from fastapi import APIRouter

from agflow.services.api_keys_service import SCOPE_CATALOGUE

router = APIRouter(
    prefix="/api/v1",
    tags=["public-scopes"],
)


@router.get("/scopes")
async def list_scopes() -> list[dict]:
    return SCOPE_CATALOGUE
