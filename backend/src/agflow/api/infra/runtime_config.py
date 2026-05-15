from __future__ import annotations

from fastapi import APIRouter, Depends

from agflow.auth.dependencies import require_operator as require_admin
from agflow.db.pool import fetch_all
from agflow.schemas.infra import RuntimeConfigEntry

router = APIRouter(prefix="/api/infra/runtime-config", tags=["infra-runtime-config"])


@router.get("", response_model=list[RuntimeConfigEntry], dependencies=[Depends(require_admin)])
async def list_runtime_config():
    rows = await fetch_all(
        "SELECT key, value, filter FROM runtime_config ORDER BY key"
    )
    return [RuntimeConfigEntry(**r) for r in rows]
