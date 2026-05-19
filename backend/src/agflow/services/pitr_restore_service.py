"""PITR restore — public API for start_clone.

`_provision_clone` is a placeholder here (T13 fills it in).
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import structlog

from agflow.db.pool import fetch_one
from agflow.schemas.pitr import RestoreWindow

log = structlog.get_logger(__name__)

CLONE_TTL_HOURS = 24


class RestoreWindowEmptyError(LookupError):
    """No OK basebackups with a populated recovery window."""


class InvalidTargetTimeError(ValueError):
    """target_time is outside the available restore window."""


class CloneAlreadyActiveError(RuntimeError):
    """A clone is already in status restoring/ready/terminating."""


async def get_restore_window() -> RestoreWindow:
    row = await fetch_one(
        "SELECT min(recovery_window_start) AS earliest, "
        "       max(recovery_window_end) AS latest "
        "FROM pitr_basebackups "
        "WHERE status = 'ok' "
        "  AND recovery_window_start IS NOT NULL "
        "  AND recovery_window_end IS NOT NULL"
    )
    if row is None or row["earliest"] is None or row["latest"] is None:
        raise RestoreWindowEmptyError("no basebackup with a valid recovery window")
    return RestoreWindow(earliest=row["earliest"], latest=row["latest"])


async def start_clone(target_time: datetime, *, actor_user_id: UUID | None) -> UUID:
    """Validate target_time, pick a basebackup, INSERT a 'restoring' clone row.

    Background `_provision_clone` is dispatched and the clone UUID is returned
    immediately so the API responds 202 Accepted without blocking.
    """
    win = await get_restore_window()
    if target_time < win.earliest or target_time > win.latest:
        raise InvalidTargetTimeError(
            f"target_time {target_time.isoformat()} is out of restore window "
            f"[{win.earliest.isoformat()}, {win.latest.isoformat()}]"
        )

    active = await fetch_one(
        "SELECT id FROM pitr_clones "
        "WHERE status IN ('restoring', 'ready', 'terminating') LIMIT 1"
    )
    if active:
        raise CloneAlreadyActiveError(str(active["id"]))

    basebackup = await fetch_one(
        "SELECT id, pgbackrest_label FROM pitr_basebackups "
        "WHERE status = 'ok' AND recovery_window_end >= $1 "
        "ORDER BY started_at ASC LIMIT 1",
        target_time,
    )
    if basebackup is None:
        raise InvalidTargetTimeError(
            f"no basebackup covers target_time {target_time.isoformat()}"
        )

    expires_at = datetime.now(UTC) + timedelta(hours=CLONE_TTL_HOURS)
    row = await fetch_one(
        "INSERT INTO pitr_clones (basebackup_id, target_time, status, expires_at, "
        "created_by_user_id) "
        "VALUES ($1, $2, 'restoring', $3, $4) RETURNING id",
        basebackup["id"], target_time, expires_at, actor_user_id,
    )
    if row is None:
        raise RuntimeError("INSERT pitr_clones returned no row")
    clone_id: UUID = row["id"]

    log.info(
        "pitr.clone.requested",
        clone_id=str(clone_id),
        basebackup_id=str(basebackup["id"]),
        target_time=target_time.isoformat(),
        actor_user_id=str(actor_user_id) if actor_user_id else None,
    )

    # Background provisioning — implemented in T13
    # RUF006: keep a reference so the task isn't silently GC'd before completion
    _task = asyncio.create_task(_provision_clone(clone_id))
    del _task  # intentional: fire-and-forget; T13 adds proper error handling
    return clone_id


async def _provision_clone(clone_id: UUID) -> None:
    """Spin up the actual postgres clone + pgweb containers.

    Placeholder for T13. Will be replaced with the full implementation
    that creates a docker volume + network + 2 containers + healthcheck.
    For T12, the call is queued via asyncio.create_task but raises here
    so any test running without mocking sees a clear failure.
    """
    raise NotImplementedError("_provision_clone is implemented in T13")
