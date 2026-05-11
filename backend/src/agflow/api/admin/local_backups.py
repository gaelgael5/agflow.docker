from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException

from agflow.auth.dependencies import require_admin
from agflow.db.pool import get_pool
from agflow.schemas.local_backups import LocalBackupSummary
from agflow.services import (
    local_backups_service,
)
from agflow.services import (
    remote_backup_connections_service as rbc_service,
)
from agflow.services.remote_backup_providers import RemoteBackupProviderError
from agflow.services.remote_backup_providers.factory import get_provider

_log = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/admin/local-backups",
    tags=["admin", "local-backups"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[LocalBackupSummary])
async def list_backups() -> list[LocalBackupSummary]:
    return await local_backups_service.list_backups()


@router.post("", response_model=LocalBackupSummary, status_code=201)
async def create_backup(
    _user_id: str = Depends(require_admin),
) -> LocalBackupSummary:
    """Déclenche un pg_dump et le sauvegarde sur disque."""
    return await local_backups_service.create_backup(created_by_user_id=None)


@router.post("/{backup_id}/push-to-remote/{remote_id}", status_code=200)
async def push_to_remote(backup_id: UUID, remote_id: UUID) -> dict:
    """Push un backup local vers une connexion distante (usage 'full')."""
    backup = await local_backups_service.get_backup(backup_id)
    if backup is None:
        raise HTTPException(status_code=404, detail="Backup not found")
    if backup.status != "completed":
        raise HTTPException(status_code=422, detail=f"Backup status is {backup.status!r}")

    async with (await get_pool()).acquire() as conn:
        connection = await rbc_service.get_connection(conn, remote_id)
        if connection is None:
            raise HTTPException(status_code=404, detail="Remote connection not found")
        credentials = await rbc_service.fetch_credentials(connection)

    if credentials is None:
        raise HTTPException(status_code=422, detail="No credentials configured for this remote")

    remote_path = rbc_service.resolve_remote_path(connection.config, connection.kind, "full")
    if remote_path is None:
        raise HTTPException(
            status_code=422, detail="No full backup path configured on this remote"
        )

    try:
        provider = get_provider(connection.kind, connection.config, credentials)
        source = await local_backups_service.stream_backup_chunks(backup_id)
        written = await provider.upload_stream(remote_path, backup.filename, source)
        _log.info(
            "push_to_remote.success",
            backup_id=str(backup_id),
            remote_id=str(remote_id),
            bytes=written,
        )
        return {"ok": True, "bytes_written": written}
    except RemoteBackupProviderError as exc:
        _log.warning("push_to_remote.provider_error", error=str(exc))
        raise HTTPException(status_code=422, detail=str(exc)) from exc
