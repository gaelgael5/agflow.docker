"""Service backup_schedules — CRUD planifications full + validation cron."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import structlog
from apscheduler.triggers.cron import CronTrigger

from agflow.db.pool import execute, fetch_all, fetch_one, get_pool
from agflow.schemas.backup_schedules import (
    FullScheduleSummary,
    ScheduleHistoryEntry,
)
from agflow.services import remote_backup_connections_service

_log = structlog.get_logger(__name__)

_FULL_SELECT_WITH_REMOTES = """
SELECT s.id, s.name, s.cron_expr, s.retention_count, s.enabled, s.keep_local,
       s.last_run_at, s.last_run_status, s.last_run_error,
       s.created_at, s.updated_at,
       coalesce(
         array_agg(r.remote_connection_id) FILTER (WHERE r.remote_connection_id IS NOT NULL),
         ARRAY[]::uuid[]
       ) AS remote_connection_ids
FROM backup_schedules_full s
LEFT JOIN backup_schedule_full_remotes r ON r.schedule_id = s.id
"""


# ── Exceptions ─────────────────────────────────────────────────────────


class ScheduleNotFoundError(Exception):
    """Schedule introuvable par id."""


class InvalidCronExpressionError(Exception):
    """Expression cron rejetée par APScheduler/croniter."""


class InvalidIntervalError(Exception):
    """interval_amount <= 0 ou unit invalide (T6)."""


class RemoteNotFoundError(Exception):
    """Remote connection introuvable par id."""


class EmptyDestinationsError(ValueError):
    """Levée si keep_local=false ET aucune remote_connection_id."""


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


# ── Full schedules CRUD ────────────────────────────────────────────────


async def list_full_schedules() -> list[FullScheduleSummary]:
    rows = await fetch_all(
        _FULL_SELECT_WITH_REMOTES + " GROUP BY s.id ORDER BY s.created_at DESC"
    )
    return [FullScheduleSummary(**dict(r)) for r in rows]


async def get_full_schedule(schedule_id: UUID) -> FullScheduleSummary:
    row = await fetch_one(
        _FULL_SELECT_WITH_REMOTES + " WHERE s.id = $1 GROUP BY s.id",
        schedule_id,
    )
    if row is None:
        raise ScheduleNotFoundError(f"Full schedule {schedule_id} not found")
    return FullScheduleSummary(**dict(row))


async def create_full_schedule(
    *,
    name: str,
    cron_expr: str,
    remote_connection_ids: list[UUID] | None = None,
    keep_local: bool = True,
    retention_count: int = 10,
    enabled: bool = True,
    actor_user_id: UUID | None = None,
) -> FullScheduleSummary:
    """Crée une planification full (multi-remote)."""
    _remote_ids: list[UUID] = remote_connection_ids if remote_connection_ids is not None else []

    # 1) Validation cron
    _validate_cron(cron_expr)

    # 2) Validation destinations (≥ 1)
    if not keep_local and not _remote_ids:
        raise EmptyDestinationsError(
            "at least one destination required (local or remote)"
        )

    # 3) Validation chaque remote existe
    for rid in _remote_ids:
        conn = await remote_backup_connections_service.get_connection(None, rid)
        if conn is None:
            raise RemoteNotFoundError(str(rid))

    # 4) Transaction : schedule + N remotes
    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        row = await conn.fetchrow(
            "INSERT INTO backup_schedules_full "
            "(name, cron_expr, retention_count, enabled, keep_local, created_by_user_id) "
            "VALUES ($1, $2, $3, $4, $5, $6) RETURNING id",
            name, cron_expr, retention_count, enabled, keep_local, actor_user_id,
        )
        schedule_id = row["id"]
        for rid in _remote_ids:
            await conn.execute(
                "INSERT INTO backup_schedule_full_remotes (schedule_id, remote_connection_id) "
                "VALUES ($1, $2)",
                schedule_id, rid,
            )

    _log.info(
        "backup_schedules.full.created",
        schedule_id=str(schedule_id),
        remote_count=len(_remote_ids),
        keep_local=keep_local,
    )
    return await get_full_schedule(schedule_id)


async def update_full_schedule(
    schedule_id: UUID,
    *,
    name: str | None = None,
    cron_expr: str | None = None,
    remote_connection_ids: list[UUID] | None = None,
    keep_local: bool | None = None,
    retention_count: int | None = None,
    enabled: bool | None = None,
) -> FullScheduleSummary:
    """Met à jour une planification full (multi-remote). Tous les champs sont optionnels."""
    # Validation cron si fourni
    if cron_expr is not None:
        _validate_cron(cron_expr)

    # Validation chaque remote existe
    if remote_connection_ids is not None:
        for rid in remote_connection_ids:
            conn = await remote_backup_connections_service.get_connection(None, rid)
            if conn is None:
                raise RemoteNotFoundError(str(rid))

    # Validation destinations (état final)
    current = await get_full_schedule(schedule_id)
    final_keep_local = keep_local if keep_local is not None else current.keep_local
    final_remote_ids = remote_connection_ids if remote_connection_ids is not None else current.remote_connection_ids
    if not final_keep_local and not final_remote_ids:
        raise EmptyDestinationsError(
            "at least one destination required (local or remote)"
        )

    pool = await get_pool()
    async with pool.acquire() as conn, conn.transaction():
        sets: list[str] = []
        params: list[Any] = []
        if name is not None:
            params.append(name)
            sets.append(f"name = ${len(params)}")
        if cron_expr is not None:
            params.append(cron_expr)
            sets.append(f"cron_expr = ${len(params)}")
        if retention_count is not None:
            params.append(retention_count)
            sets.append(f"retention_count = ${len(params)}")
        if enabled is not None:
            params.append(enabled)
            sets.append(f"enabled = ${len(params)}")
        if keep_local is not None:
            params.append(keep_local)
            sets.append(f"keep_local = ${len(params)}")
        if sets:
            params.append(schedule_id)
            await conn.execute(
                f"UPDATE backup_schedules_full SET {', '.join(sets)} WHERE id = ${len(params)}",
                *params,
            )

        if remote_connection_ids is not None:
            await conn.execute(
                "DELETE FROM backup_schedule_full_remotes WHERE schedule_id = $1",
                schedule_id,
            )
            for rid in remote_connection_ids:
                await conn.execute(
                    "INSERT INTO backup_schedule_full_remotes (schedule_id, remote_connection_id) "
                    "VALUES ($1, $2)",
                    schedule_id, rid,
                )

    _log.info("backup_schedules.full.updated", id=str(schedule_id))
    return await get_full_schedule(schedule_id)


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
        "UPDATE backup_schedules_full SET enabled = $2 "
        "WHERE id = $1 RETURNING id",
        schedule_id, enabled,
    )
    if row is None:
        raise ScheduleNotFoundError(f"Full schedule {schedule_id} not found")
    _log.info(
        "backup_schedules.full.set_enabled",
        id=str(schedule_id), enabled=enabled,
    )
    return await get_full_schedule(schedule_id)


# ── Cross-kind helpers ─────────────────────────────────────────────────


async def record_run(
    *,
    schedule_id: UUID,
    kind: Literal["full"],
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
    kind: Literal["full"],
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
