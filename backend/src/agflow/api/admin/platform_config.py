from __future__ import annotations

from fastapi import APIRouter, Depends

from agflow.auth.dependencies import require_operator as require_admin
from agflow.config import get_settings

router = APIRouter(
    prefix="/api/admin/platform-config",
    tags=["admin-platform-config"],
    dependencies=[Depends(require_admin)],
)


@router.get("")
async def get_platform_config() -> dict[str, str]:
    s = get_settings()
    return {
        "grafana_url": s.grafana_url.rstrip("/"),
    }
