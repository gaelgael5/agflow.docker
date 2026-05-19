"""Singleton config + N-N remotes pour PITR (pgBackRest)."""
from __future__ import annotations

from uuid import UUID

import structlog
from apscheduler.triggers.cron import CronTrigger

from agflow.db import pool
from agflow.schemas.pitr import PitrConfigOut

log = structlog.get_logger(__name__)


class InvalidCronError(ValueError):
    """Raised when basebackup_cron does not parse via APScheduler CronTrigger."""


def _validate_cron(expr: str) -> None:
    """Valide une expression cron 5-fields via APScheduler.CronTrigger.from_crontab.

    Lève InvalidCronError si l'expression est invalide.
    """
    try:
        CronTrigger.from_crontab(expr)
    except (ValueError, TypeError) as exc:
        raise InvalidCronError(f"invalid cron expression {expr!r}: {exc}") from exc


async def get_config() -> PitrConfigOut:
    """Retourne la configuration PITR (singleton row id=1) avec les remotes associés."""
    row = await pool.fetch_one(
        "SELECT enabled, basebackup_cron, retention_count, updated_at "
        "FROM pitr_config WHERE id = 1"
    )
    if row is None:
        raise RuntimeError(
            "pitr_config singleton row missing — migration 111 not applied"
        )
    remote_rows = await pool.fetch_all(
        "SELECT remote_connection_id FROM pitr_config_remotes "
        "WHERE config_id = 1 ORDER BY remote_connection_id"
    )
    return PitrConfigOut(
        enabled=row["enabled"],
        basebackup_cron=row["basebackup_cron"],
        retention_count=row["retention_count"],
        updated_at=row["updated_at"],
        remote_connection_ids=[r["remote_connection_id"] for r in remote_rows],
    )


async def update_config(
    *,
    enabled: bool | None = None,
    basebackup_cron: str | None = None,
    retention_count: int | None = None,
    remote_connection_ids: list[UUID] | None = None,
) -> PitrConfigOut:
    """Met à jour la configuration PITR (singleton row id=1).

    Seuls les paramètres fournis (non-None) sont modifiés.
    Si remote_connection_ids est fourni (liste éventuellement vide),
    la table pitr_config_remotes est entièrement remplacée.

    Raises:
        InvalidCronError: si basebackup_cron ne parse pas via CronTrigger.
    """
    if basebackup_cron is not None:
        _validate_cron(basebackup_cron)

    db_pool = await pool.get_pool()
    async with db_pool.acquire() as conn, conn.transaction():
        sets: list[str] = []
        params: list[object] = []

        if enabled is not None:
            params.append(enabled)
            sets.append(f"enabled = ${len(params)}")
        if basebackup_cron is not None:
            params.append(basebackup_cron)
            sets.append(f"basebackup_cron = ${len(params)}")
        if retention_count is not None:
            params.append(retention_count)
            sets.append(f"retention_count = ${len(params)}")

        if sets:
            await conn.execute(
                f"UPDATE pitr_config SET {', '.join(sets)} WHERE id = 1",
                *params,
            )

        if remote_connection_ids is not None:
            await conn.execute(
                "DELETE FROM pitr_config_remotes WHERE config_id = 1"
            )
            for rid in remote_connection_ids:
                await conn.execute(
                    "INSERT INTO pitr_config_remotes (config_id, remote_connection_id) "
                    "VALUES (1, $1)",
                    rid,
                )

    return await get_config()
