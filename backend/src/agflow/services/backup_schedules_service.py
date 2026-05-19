"""Service backup_schedules — CRUD planifications + validation cron.

Snapshot CRUD + record_run + prune_old_backups dans Task 6.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import structlog
from apscheduler.triggers.cron import CronTrigger

from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.schemas.backup_schedules import (
    FullScheduleCreate,
    FullScheduleSummary,
    FullScheduleUpdate,
    ScheduleHistoryEntry,
    SnapshotScheduleCreate,
    SnapshotScheduleSummary,
    SnapshotScheduleUpdate,
)

_log = structlog.get_logger(__name__)

_FULL_COLS = (
    "id, name, cron_expr, remote_connection_id, retention_count, enabled, "
    "last_run_at, last_run_status, last_run_error, created_at, updated_at"
)

_SNAPSHOT_COLS = (
    "id, name, interval_amount, interval_unit, remote_connection_id, retention_count, enabled, "
    "last_run_at, last_run_status, last_run_error, created_at, updated_at"
)


# ── Exceptions ─────────────────────────────────────────────────────────


class ScheduleNotFoundError(Exception):
    """Schedule introuvable par id."""


class InvalidCronExpressionError(Exception):
    """Expression cron rejetée par APScheduler/croniter."""


class InvalidIntervalError(Exception):
    """interval_amount <= 0 ou unit invalide (T6)."""


# ── Helpers ────────────────────────────────────────────────────────────


def _validate_cron(expr: str) -> None:
    """Valide une expression cron 5-fields via APScheduler.

    APScheduler.CronTrigger.from_crontab accepte le format standard
    (minute heure jour mois jour-semaine). Lève ValueError si invalide,
    qu'on convertit en InvalidCronExpressionError pour mapping HTTP propre.
    """
    try:
        CronTrigger.from_crontab(expr)
    except (ValueError, TypeError) as exc:
        raise InvalidCronExpressionError(
            f"Invalid cron expression {expr!r}: {exc}"
        ) from exc


def _to_full_summary(row: dict[str, Any]) -> FullScheduleSummary:
    return FullScheduleSummary(
        id=row["id"],
        name=row["name"],
        cron_expr=row["cron_expr"],
        remote_connection_id=row["remote_connection_id"],
        retention_count=row["retention_count"],
        enabled=row["enabled"],
        last_run_at=row["last_run_at"],
        last_run_status=row["last_run_status"],
        last_run_error=row["last_run_error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _to_snapshot_summary(row: dict[str, Any]) -> SnapshotScheduleSummary:
    return SnapshotScheduleSummary(
        id=row["id"],
        name=row["name"],
        interval_amount=row["interval_amount"],
        interval_unit=row["interval_unit"],
        remote_connection_id=row["remote_connection_id"],
        retention_count=row["retention_count"],
        enabled=row["enabled"],
        last_run_at=row["last_run_at"],
        last_run_status=row["last_run_status"],
        last_run_error=row["last_run_error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


# ── Full schedules CRUD ────────────────────────────────────────────────


async def list_full_schedules() -> list[FullScheduleSummary]:
    rows = await fetch_all(
        f"SELECT {_FULL_COLS} FROM backup_schedules_full ORDER BY name",
    )
    return [_to_full_summary(r) for r in rows]


async def get_full_schedule(schedule_id: UUID) -> FullScheduleSummary:
    row = await fetch_one(
        f"SELECT {_FULL_COLS} FROM backup_schedules_full WHERE id = $1",
        schedule_id,
    )
    if row is None:
        raise ScheduleNotFoundError(f"Full schedule {schedule_id} not found")
    return _to_full_summary(row)


async def create_full_schedule(
    payload: FullScheduleCreate,
    *,
    actor_user_id: UUID | None = None,
) -> FullScheduleSummary:
    _validate_cron(payload.cron_expr)
    row = await fetch_one(
        f"""
        INSERT INTO backup_schedules_full
            (name, cron_expr, remote_connection_id, retention_count, enabled, created_by_user_id)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING {_FULL_COLS}
        """,
        payload.name, payload.cron_expr, payload.remote_connection_id,
        payload.retention_count, payload.enabled, actor_user_id,
    )
    assert row is not None
    _log.info(
        "backup_schedules.full.created",
        id=str(row["id"]), name=payload.name, cron=payload.cron_expr,
    )
    return _to_full_summary(row)


async def update_full_schedule(
    schedule_id: UUID, payload: FullScheduleUpdate,
) -> FullScheduleSummary:
    await get_full_schedule(schedule_id)  # 404 check

    if payload.cron_expr is not None:
        _validate_cron(payload.cron_expr)

    sets: list[str] = []
    args: list[Any] = [schedule_id]
    i = 2
    for field in ("name", "cron_expr", "remote_connection_id", "retention_count", "enabled"):
        val = getattr(payload, field)
        if val is not None:
            sets.append(f"{field} = ${i}")
            args.append(val)
            i += 1

    if not sets:
        return await get_full_schedule(schedule_id)

    row = await fetch_one(
        f"UPDATE backup_schedules_full SET {', '.join(sets)} "
        f"WHERE id = $1 RETURNING {_FULL_COLS}",
        *args,
    )
    assert row is not None
    _log.info("backup_schedules.full.updated", id=str(schedule_id))
    return _to_full_summary(row)


async def delete_full_schedule(schedule_id: UUID) -> None:
    row = await fetch_one(
        "DELETE FROM backup_schedules_full WHERE id = $1 RETURNING id",
        schedule_id,
    )
    if row is None:
        raise ScheduleNotFoundError(f"Full schedule {schedule_id} not found")
    _log.info("backup_schedules.full.deleted", id=str(schedule_id))


async def set_full_enabled(
    schedule_id: UUID, enabled: bool,
) -> FullScheduleSummary:
    row = await fetch_one(
        f"UPDATE backup_schedules_full SET enabled = $2 "
        f"WHERE id = $1 RETURNING {_FULL_COLS}",
        schedule_id, enabled,
    )
    if row is None:
        raise ScheduleNotFoundError(f"Full schedule {schedule_id} not found")
    _log.info(
        "backup_schedules.full.set_enabled",
        id=str(schedule_id), enabled=enabled,
    )
    return _to_full_summary(row)


# ── Snapshot schedules CRUD ────────────────────────────────────────────


async def list_snapshot_schedules() -> list[SnapshotScheduleSummary]:
    rows = await fetch_all(
        f"SELECT {_SNAPSHOT_COLS} FROM backup_schedules_snapshot ORDER BY name",
    )
    return [_to_snapshot_summary(r) for r in rows]


async def get_snapshot_schedule(schedule_id: UUID) -> SnapshotScheduleSummary:
    row = await fetch_one(
        f"SELECT {_SNAPSHOT_COLS} FROM backup_schedules_snapshot WHERE id = $1",
        schedule_id,
    )
    if row is None:
        raise ScheduleNotFoundError(f"Snapshot schedule {schedule_id} not found")
    return _to_snapshot_summary(row)


async def create_snapshot_schedule(
    payload: SnapshotScheduleCreate,
    *,
    actor_user_id: UUID | None = None,
) -> SnapshotScheduleSummary:
    row = await fetch_one(
        f"""
        INSERT INTO backup_schedules_snapshot
            (name, interval_amount, interval_unit, remote_connection_id,
             retention_count, enabled, created_by_user_id)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        RETURNING {_SNAPSHOT_COLS}
        """,
        payload.name, payload.interval_amount, payload.interval_unit,
        payload.remote_connection_id, payload.retention_count,
        payload.enabled, actor_user_id,
    )
    assert row is not None
    _log.info(
        "backup_schedules.snapshot.created",
        id=str(row["id"]), name=payload.name,
        interval=f"{payload.interval_amount} {payload.interval_unit}",
    )
    return _to_snapshot_summary(row)


async def update_snapshot_schedule(
    schedule_id: UUID, payload: SnapshotScheduleUpdate,
) -> SnapshotScheduleSummary:
    await get_snapshot_schedule(schedule_id)  # 404 check

    sets: list[str] = []
    args: list[Any] = [schedule_id]
    i = 2
    for field in (
        "name", "interval_amount", "interval_unit",
        "remote_connection_id", "retention_count", "enabled",
    ):
        val = getattr(payload, field)
        if val is not None:
            sets.append(f"{field} = ${i}")
            args.append(val)
            i += 1

    if not sets:
        return await get_snapshot_schedule(schedule_id)

    row = await fetch_one(
        f"UPDATE backup_schedules_snapshot SET {', '.join(sets)} "
        f"WHERE id = $1 RETURNING {_SNAPSHOT_COLS}",
        *args,
    )
    assert row is not None
    _log.info("backup_schedules.snapshot.updated", id=str(schedule_id))
    return _to_snapshot_summary(row)


async def delete_snapshot_schedule(schedule_id: UUID) -> None:
    row = await fetch_one(
        "DELETE FROM backup_schedules_snapshot WHERE id = $1 RETURNING id",
        schedule_id,
    )
    if row is None:
        raise ScheduleNotFoundError(f"Snapshot schedule {schedule_id} not found")
    _log.info("backup_schedules.snapshot.deleted", id=str(schedule_id))


async def set_snapshot_enabled(
    schedule_id: UUID, enabled: bool,
) -> SnapshotScheduleSummary:
    row = await fetch_one(
        f"UPDATE backup_schedules_snapshot SET enabled = $2 "
        f"WHERE id = $1 RETURNING {_SNAPSHOT_COLS}",
        schedule_id, enabled,
    )
    if row is None:
        raise ScheduleNotFoundError(f"Snapshot schedule {schedule_id} not found")
    _log.info(
        "backup_schedules.snapshot.set_enabled",
        id=str(schedule_id), enabled=enabled,
    )
    return _to_snapshot_summary(row)


# ── Cross-kind helpers ─────────────────────────────────────────────────


async def record_run(
    *,
    schedule_id: UUID,
    kind: Literal["full", "snapshot"],
    status: Literal["ok", "failed"],
    error: str | None = None,
) -> None:
    """Update last_run_* sur le schedule. UNIQUEMENT au runtime du job_runner."""
    table = f"backup_schedules_{kind}"
    # Tronque l'erreur à 500 chars pour éviter de remplir la DB avec des traces.
    truncated_error = (error[:500] if error else None)
    await execute(
        f"UPDATE {table} SET "
        f"last_run_at = $2, last_run_status = $3, last_run_error = $4 "
        f"WHERE id = $1",
        schedule_id, datetime.now(UTC), status, truncated_error,
    )


async def prune_old_backups(
    *,
    schedule_id: UUID,
    kind: Literal["full", "snapshot"],
    retention_count: int,
) -> int:
    """Supprime les backups les plus anciens du schedule au-delà de retention_count.

    Retourne le nombre de backups supprimés (DB row + fichier disque).
    """
    column = f"source_schedule_{kind}_id"
    # Liste les backups à supprimer (au-delà du Nème plus récent)
    rows_to_delete = await fetch_all(
        f"""
        SELECT id, file_path FROM local_backups
        WHERE {column} = $1
        ORDER BY created_at DESC
        OFFSET $2
        """,
        schedule_id, retention_count,
    )
    deleted = 0
    for row in rows_to_delete:
        try:
            Path(row["file_path"]).unlink(missing_ok=True)
        except OSError as exc:
            _log.warning(
                "backup_schedules.prune.file_unlink_failed",
                schedule_id=str(schedule_id), file=row["file_path"],
                error=str(exc),
            )
        await execute("DELETE FROM local_backups WHERE id = $1", row["id"])
        deleted += 1

    if deleted > 0:
        _log.info(
            "backup_schedules.prune.done",
            schedule_id=str(schedule_id), kind=kind, deleted=deleted,
        )
    return deleted


# ── History ────────────────────────────────────────────────────────────


async def list_history_full(schedule_id: UUID, limit: int = 50) -> list[ScheduleHistoryEntry]:
    """Liste les runs (local_backups) attachés à une full schedule."""
    rows = await fetch_all(
        """
        SELECT id, filename, file_path, size_bytes, status,
               created_at, created_by_user_id
        FROM local_backups
        WHERE source_schedule_full_id = $1
        ORDER BY created_at DESC
        LIMIT $2
        """,
        schedule_id,
        limit,
    )
    return [ScheduleHistoryEntry(**dict(r)) for r in rows]


async def list_history_snapshot(schedule_id: UUID, limit: int = 50) -> list[ScheduleHistoryEntry]:
    """Liste les runs (local_backups) attachés à une snapshot schedule."""
    rows = await fetch_all(
        """
        SELECT id, filename, file_path, size_bytes, status,
               created_at, created_by_user_id
        FROM local_backups
        WHERE source_schedule_snapshot_id = $1
        ORDER BY created_at DESC
        LIMIT $2
        """,
        schedule_id,
        limit,
    )
    return [ScheduleHistoryEntry(**dict(r)) for r in rows]
