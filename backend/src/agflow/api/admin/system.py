"""Admin endpoints touching system-level concerns (data export, etc.)."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse

from agflow.auth.dependencies import require_admin
from agflow.services import db_backup
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


@router.get("/db/export", summary="Download a gzipped pg_dump of the Postgres database")
async def export_db(
    _user_id: str = Depends(require_admin),
) -> StreamingResponse:
    filename = db_backup.export_filename()
    return StreamingResponse(
        db_backup.stream_dump(),
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/db/import", summary="Restore the Postgres database from a gzipped pg_dump")
async def import_db(
    file: UploadFile,
    _user_id: str = Depends(require_admin),
) -> dict:
    """⚠️ Destructif — le dump utilisé contient --clean --if-exists, donc
    toutes les tables existantes sont DROP avant recréation.
    """

    async def _chunks():
        while True:
            chunk = await file.read(64 * 1024)
            if not chunk:
                break
            yield chunk

    result = await db_backup.restore_dump(_chunks())
    if result["exit_code"] != 0:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"psql exited with code {result['exit_code']}: {result['tail']}",
        )
    return {"status": "ok", "exit_code": result["exit_code"]}
