"""Admin endpoints touching system-level concerns (data export, etc.)."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from agflow.auth.dependencies import require_admin
from agflow.services.system_export import export_filename, iter_data_zip

router = APIRouter(
    prefix="/api/admin/system",
    tags=["admin-system"],
    dependencies=[Depends(require_admin)],
)


def _data_dir() -> Path:
    return Path(os.environ.get("AGFLOW_DATA_DIR", "/app/data"))


@router.get("/export")
async def export_data_volume(
    user_id: str = Depends(require_admin),
) -> StreamingResponse:
    filename = export_filename()
    return StreamingResponse(
        iter_data_zip(_data_dir(), user_id=user_id),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
