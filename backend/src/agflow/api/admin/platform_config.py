from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from agflow.auth.dependencies import require_operator as require_admin
from agflow.config import get_settings
from agflow.services import dozzle_sync_service

router = APIRouter(
    prefix="/api/admin/platform-config",
    tags=["admin-platform-config"],
    dependencies=[Depends(require_admin)],
)


@router.get("")
async def get_platform_config() -> dict[str, str]:
    s = get_settings()
    return {
        "dozzle_url": s.dozzle_url.rstrip("/"),
    }


@router.post("/dozzle-sync")
async def dozzle_resync() -> dict[str, Any]:
    """Recompute the DOZZLE_REMOTE_AGENT list from machines and restart dozzle."""
    return await dozzle_sync_service.sync()
