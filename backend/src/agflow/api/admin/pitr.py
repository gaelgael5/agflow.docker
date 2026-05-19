"""PITR admin API — config + basebackups + WAL + clones.

Endpoints incrementally added:
- T17: GET/PUT /config
- T18: basebackups (5 endpoints)
- T19: wal-status + restore-window (2 endpoints)
- T20: clones (4 endpoints)
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from agflow.auth.dependencies import require_admin
from agflow.schemas.pitr import PitrConfigOut, PitrConfigUpdate
from agflow.services import pitr_config_service, pitr_scheduler

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
