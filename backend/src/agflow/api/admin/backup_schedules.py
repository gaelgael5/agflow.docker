"""Router admin pour les planifications de backups full (cron).

6 endpoints sous /api/admin/backup-schedules — require_admin global.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from agflow.auth.dependencies import require_admin
from agflow.schemas.backup_schedules import (
    FullScheduleCreate,
    FullScheduleSummary,
    FullScheduleUpdate,
    ScheduleHistoryEntry,
)
from agflow.services import (
    backup_scheduler,
    users_service,
)
from agflow.services import (
    backup_schedules_service as svc,
)

router = APIRouter(
    prefix="/api/admin/backup-schedules",
    tags=["admin-backup-schedules"],
    dependencies=[Depends(require_admin)],
)


class SetEnabledRequest(BaseModel):
    enabled: bool


# ── Full schedules ─────────────────────────────────────────────────────


@router.get("/full", response_model=list[FullScheduleSummary])
async def list_full() -> list[FullScheduleSummary]:
    return await svc.list_full_schedules()


@router.post(
    "/full",
    response_model=FullScheduleSummary,
    status_code=status.HTTP_201_CREATED,
)
async def create_full(
    payload: FullScheduleCreate,
    admin_email: str = Depends(require_admin),
) -> FullScheduleSummary:
    admin_user = await users_service.get_by_email(admin_email)
    actor_id = admin_user.id if admin_user else None
    try:
        return await svc.create_full_schedule(payload, actor_user_id=actor_id)
    except svc.InvalidCronExpressionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc),
        ) from exc


@router.put("/full/{schedule_id}", response_model=FullScheduleSummary)
async def update_full(
    schedule_id: UUID, payload: FullScheduleUpdate,
) -> FullScheduleSummary:
    try:
        return await svc.update_full_schedule(schedule_id, payload)
    except svc.ScheduleNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except svc.InvalidCronExpressionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc),
        ) from exc


@router.delete(
    "/full/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_full(schedule_id: UUID) -> None:
    try:
        await svc.delete_full_schedule(schedule_id)
    except svc.ScheduleNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/full/{schedule_id}/run-now",
    status_code=status.HTTP_202_ACCEPTED,
)
async def run_now_full(schedule_id: UUID) -> dict:
    try:
        await svc.get_full_schedule(schedule_id)  # 404 check
    except svc.ScheduleNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    await backup_scheduler.trigger_now(schedule_id=schedule_id)
    return {"triggered": True}


@router.get(
    "/full/{schedule_id}/history",
    response_model=list[ScheduleHistoryEntry],
)
async def get_full_history(
    schedule_id: UUID,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ScheduleHistoryEntry]:
    try:
        await svc.get_full_schedule(schedule_id)
    except svc.ScheduleNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return await svc.list_history_full(schedule_id, limit=limit)


@router.post("/full/{schedule_id}/set-enabled", response_model=FullScheduleSummary)
async def set_full_enabled(
    schedule_id: UUID, payload: SetEnabledRequest,
) -> FullScheduleSummary:
    try:
        return await svc.set_full_enabled(schedule_id, payload.enabled)
    except svc.ScheduleNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


