from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException

from agflow.auth.dependencies import require_admin
from agflow.db.pool import get_pool
from agflow.schemas.local_backup_pushes import LocalBackupPushSummary
from agflow.schemas.local_backups import LocalBackupSummary, ScanResult
from agflow.schemas.remote_backup_files import PullRequest, RestoreResult
from agflow.services import (
    local_backup_pushes_service,
    local_backups_service,
    restore_service,
    users_service,
)
from agflow.services import remote_backup_connections_service as rbc_service
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
    admin_email: str = Depends(require_admin),
) -> LocalBackupSummary:
    """Déclenche un pg_dump et le sauvegarde sur disque."""
    admin_user = await users_service.get_by_email(admin_email)
    user_uuid = admin_user.id if admin_user else None
    return await local_backups_service.create_backup(created_by_user_id=user_uuid)


@router.delete("/{backup_id}", status_code=204)
async def delete_backup(backup_id: UUID) -> None:
    """Suppression complète d'un local_backup : fichier + pushes + row."""
    try:
        await local_backups_service.delete_backup(backup_id)
    except local_backups_service.BackupNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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
        credentials = await rbc_service.inject_certificate_credentials(
            connection.config, credentials
        )
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


@router.post(
    "/pull-from-remote/{remote_id}",
    response_model=LocalBackupSummary,
    status_code=201,
)
async def pull_from_remote(
    remote_id: UUID,
    body: PullRequest,
    admin_email: str = Depends(require_admin),
) -> LocalBackupSummary:
    """Pull un fichier distant vers les backups locaux."""
    admin_user = await users_service.get_by_email(admin_email)
    user_uuid = admin_user.id if admin_user else None
    try:
        return await local_backups_service.pull_remote_to_local(
            remote_id,
            filename=body.filename,
            created_by_user_id=user_uuid,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/{backup_id}/restore", response_model=RestoreResult, status_code=200)
async def restore_backup(backup_id: UUID, body: PullRequest) -> RestoreResult:
    """Restaure (DROP + recreate) un backup local dans Postgres.

    L'admin doit retaper exactement le filename pour confirmer l'action destructive.
    """
    backup = await local_backups_service.get_backup(backup_id)
    if backup is None:
        raise HTTPException(status_code=404, detail="Backup not found")
    if body.filename != backup.filename:
        raise HTTPException(
            status_code=422,
            detail=f"Filename does not match (expected {backup.filename!r})",
        )
    try:
        return await restore_service.restore_local_backup(backup_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/scan-schedules", response_model=ScanResult, status_code=200)
async def scan_schedules() -> ScanResult:
    """Scanne les remotes de chaque planification full et reconstruit l'historique en DB."""
    return await local_backups_service.scan_from_schedules()


@router.get("/{backup_id}/pushes", response_model=list[LocalBackupPushSummary])
async def list_pushes(backup_id: UUID) -> list[LocalBackupPushSummary]:
    """Liste les pushes (1 par remote configurée) d'un local_backup."""
    return await local_backup_pushes_service.list_pushes(backup_id)


@router.post("/{backup_id}/push/{remote_id}", status_code=202)
async def push_backup(backup_id: UUID, remote_id: UUID) -> dict[str, str]:
    """Re-push manuel d'un local_backup vers une remote (utile si push initial échoué)."""
    try:
        result = await local_backup_pushes_service.push_one(
            backup_id=backup_id, remote_id=remote_id
        )
    except local_backup_pushes_service.PushNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"push not found: {exc}") from exc
    except local_backup_pushes_service.LocalFileMissingError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"local file missing: {exc}",
        ) from exc
    return {"status": result.status}
