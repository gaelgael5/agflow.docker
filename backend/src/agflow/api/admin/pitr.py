"""PITR admin API — config + basebackups + WAL + clones.

Endpoints incrementally added:
- T17: GET/PUT /config
- T18: basebackups (5 endpoints)
- T19: wal-status + restore-window (2 endpoints)
- T20: clones (4 endpoints)
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from agflow.auth.dependencies import require_admin
from agflow.schemas.pitr import (
    BasebackupSummary,
    CloneRequest,
    CloneStatus,
    PitrConfigOut,
    PitrConfigUpdate,
    RestoreWindow,
    WalStatus,
)
from agflow.services import (
    pitr_basebackup_pushes_service,
    pitr_basebackup_service,
    pitr_clone_service,
    pitr_config_service,
    pitr_restore_service,
    pitr_scheduler,
    pitr_wal_archive_service,
)

router = APIRouter(
    prefix="/api/admin/pitr",
    tags=["admin-pitr"],
    dependencies=[Depends(require_admin)],
)


@router.get("/config", response_model=PitrConfigOut)
async def get_config() -> PitrConfigOut:
    """Read the singleton PITR config row."""
    return await pitr_config_service.get_config()


@router.put("/config", response_model=PitrConfigOut)
async def update_config(payload: PitrConfigUpdate) -> PitrConfigOut:
    """Update the PITR config (cron, type, rebase cron, retention, remotes, enabled).

    422 if cron invalid. Triggers `pitr_scheduler.reload_basebackup_schedule()`
    if any of cron / type / rebase cron / enabled flag changed.
    """
    try:
        cfg = await pitr_config_service.update_config(
            enabled=payload.enabled,
            basebackup_cron=payload.basebackup_cron,
            basebackup_type=payload.basebackup_type,
            full_rebase_cron=payload.full_rebase_cron,
            retention_count=payload.retention_count,
            remote_connection_ids=payload.remote_connection_ids,
        )
    except pitr_config_service.InvalidCronError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    schedule_affecting = (
        payload.basebackup_cron is not None
        or payload.basebackup_type is not None
        or payload.full_rebase_cron is not None
        or payload.enabled is not None
    )
    if schedule_affecting:
        await pitr_scheduler.reload_basebackup_schedule()
    return cfg


# ---------------------------------------------------------------------------
# Basebackups
# ---------------------------------------------------------------------------


@router.get("/basebackups", response_model=list[BasebackupSummary])
async def list_basebackups() -> list[BasebackupSummary]:
    """List all basebackups with their push entries."""
    return await pitr_basebackup_service.list_basebackups()


@router.get("/basebackups/{basebackup_id}", response_model=BasebackupSummary)
async def get_basebackup(basebackup_id: UUID) -> BasebackupSummary:
    """Fetch a single basebackup by UUID."""
    try:
        return await pitr_basebackup_service.get_basebackup(basebackup_id)
    except pitr_basebackup_service.BasebackupNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/basebackups", status_code=202)
async def trigger_basebackup(
    actor_user_id: str = Depends(require_admin),
) -> dict[str, str]:
    """Trigger a fresh basebackup. Returns the new basebackup UUID immediately;
    the actual pgbackrest backup runs synchronously inside the service."""
    try:
        try:
            actor_uuid: UUID | None = UUID(actor_user_id) if actor_user_id else None
        except ValueError:
            actor_uuid = None
        bid = await pitr_basebackup_service.trigger_basebackup_now(
            actor_user_id=actor_uuid
        )
    except pitr_basebackup_service.BasebackupRunningError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"basebackup already running: {exc}",
        ) from exc
    return {"id": str(bid)}


@router.delete("/basebackups/{basebackup_id}", status_code=204)
async def delete_basebackup(basebackup_id: UUID) -> None:
    """Delete a basebackup. Refuses if it is the only remaining OK backup."""
    try:
        await pitr_basebackup_service.delete_basebackup(basebackup_id)
    except pitr_basebackup_service.BasebackupNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except pitr_basebackup_service.BasebackupIsLastError as exc:
        raise HTTPException(
            status_code=409,
            detail="cannot delete the only remaining basebackup",
        ) from exc


@router.post("/basebackups/{basebackup_id}/push/{remote_id}", status_code=202)
async def push_basebackup_endpoint(
    basebackup_id: UUID, remote_id: UUID
) -> dict[str, str]:
    """Re-push a basebackup to a remote storage. Returns immediately."""
    try:
        await pitr_basebackup_pushes_service.push_basebackup(basebackup_id, remote_id)
    except pitr_basebackup_pushes_service.PushNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except pitr_basebackup_service.BasebackupNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "queued"}


# ---------------------------------------------------------------------------
# WAL status + restore window
# ---------------------------------------------------------------------------


@router.get("/wal-status", response_model=WalStatus)
async def get_wal_status() -> WalStatus:
    """Current WAL archiving state, last archive timestamp, disk usage."""
    return await pitr_wal_archive_service.get_wal_status()


@router.get("/restore-window", response_model=RestoreWindow)
async def get_restore_window() -> RestoreWindow:
    """[earliest, latest] window of restorable points in time."""
    try:
        return await pitr_restore_service.get_restore_window()
    except pitr_restore_service.RestoreWindowEmptyError as exc:
        raise HTTPException(
            status_code=404,
            detail="no basebackup with a valid recovery window",
        ) from exc


# ---------------------------------------------------------------------------
# Clones
# ---------------------------------------------------------------------------


@router.post("/clones", status_code=202)
async def start_clone_endpoint(
    payload: CloneRequest,
    actor_user_id: str = Depends(require_admin),
) -> dict[str, str]:
    """Start a PITR clone at target_time. Returns the clone UUID immediately; the
    actual provisioning happens in background."""
    actor_uuid: UUID | None
    try:
        actor_uuid = UUID(actor_user_id) if actor_user_id else None
    except ValueError:
        actor_uuid = None

    try:
        clone_id = await pitr_restore_service.start_clone(
            payload.target_time, actor_user_id=actor_uuid
        )
    except pitr_restore_service.RestoreWindowEmptyError as exc:
        raise HTTPException(status_code=404, detail="no basebackup available") from exc
    except pitr_restore_service.InvalidTargetTimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except pitr_restore_service.CloneAlreadyActiveError as exc:
        raise HTTPException(status_code=409, detail=f"clone already active: {exc}") from exc
    return {"id": str(clone_id)}


@router.get("/clones/active", response_model=CloneStatus | None)
async def get_active_clone_endpoint() -> CloneStatus | None:
    """Return the current active clone, or null if none."""
    return await pitr_clone_service.get_active_clone()


@router.post("/clones/active/extend", response_model=CloneStatus)
async def extend_active_clone_endpoint() -> CloneStatus:
    """Extend the active clone TTL by 24 h."""
    try:
        return await pitr_clone_service.extend_active_clone()
    except pitr_clone_service.NoActiveCloneError as exc:
        raise HTTPException(status_code=404, detail="no active clone") from exc


@router.delete("/clones/active", status_code=204)
async def terminate_active_clone_endpoint() -> None:
    """Stop and clean up the active clone."""
    try:
        await pitr_clone_service.terminate_active_clone()
    except pitr_clone_service.NoActiveCloneError as exc:
        raise HTTPException(status_code=404, detail="no active clone") from exc
