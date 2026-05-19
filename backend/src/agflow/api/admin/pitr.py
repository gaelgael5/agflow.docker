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
from agflow.schemas.pitr import BasebackupSummary, PitrConfigOut, PitrConfigUpdate
from agflow.services import (
    pitr_basebackup_pushes_service,
    pitr_basebackup_service,
    pitr_config_service,
    pitr_scheduler,
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
    """Update the PITR config (cron, retention, remotes, enabled).

    422 if cron invalid. Triggers `pitr_scheduler.reload_basebackup_schedule()`
    if cron or enabled flag changed.
    """
    try:
        cfg = await pitr_config_service.update_config(
            enabled=payload.enabled,
            basebackup_cron=payload.basebackup_cron,
            retention_count=payload.retention_count,
            remote_connection_ids=payload.remote_connection_ids,
        )
    except pitr_config_service.InvalidCronError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    if payload.basebackup_cron is not None or payload.enabled is not None:
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
