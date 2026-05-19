"""PITR basebackup service — stanza init + list/get/trigger + delete.

Push/prune operations live in pitr_basebackup_pushes_service.py to keep
both files under 300 lines per CLAUDE.md.
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.docker.exec_helper import docker_exec
from agflow.schemas.pitr import BasebackupPushSummary, BasebackupSummary

log = structlog.get_logger(__name__)

POSTGRES_CONTAINER = "agflow-postgres"
STANZA = "agflow"

_LABEL_RE = re.compile(r"label\s*=\s*([0-9A-Za-z_\-]+)")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class BasebackupRunningError(RuntimeError):
    """Raised when a basebackup is already in progress."""


class BasebackupNotFoundError(LookupError):
    """Raised when a basebackup UUID doesn't exist."""


class BasebackupIsLastError(RuntimeError):
    """Raised when trying to delete the only OK basebackup remaining."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _pg_exec(args: list[str]) -> tuple[int, str, str]:
    """Run `pgbackrest <args>` inside the agflow-postgres container."""
    return await docker_exec(POSTGRES_CONTAINER, ["pgbackrest", *args])


async def _last_label_from_info() -> str:
    code, out, _ = await _pg_exec(["--stanza=" + STANZA, "info", "--output=json"])
    if code != 0 or not out.strip():
        raise RuntimeError("pgbackrest info returned no data")
    info = json.loads(out)
    backups = info[0].get("backup", []) if info else []
    if not backups:
        raise RuntimeError("no backup in pgbackrest info after backup command")
    return backups[-1]["label"]


async def _label_size_from_info(label: str) -> int | None:
    code, out, _ = await _pg_exec(["--stanza=" + STANZA, "info", "--output=json"])
    if code != 0 or not out.strip():
        return None
    info = json.loads(out)
    for b in info[0].get("backup", []):
        if b.get("label") == label:
            return int(b.get("info", {}).get("size") or 0)
    return None


def _row_to_basebackup_summary(r: dict[str, Any]) -> BasebackupSummary:
    pushes_raw = r["pushes"]
    if isinstance(pushes_raw, str):
        pushes_raw = json.loads(pushes_raw)
    return BasebackupSummary(
        id=r["id"],
        pgbackrest_label=r["pgbackrest_label"],
        started_at=r["started_at"],
        completed_at=r["completed_at"],
        size_bytes=r["size_bytes"],
        status=r["status"],
        error=r["error"],
        recovery_window_start=r["recovery_window_start"],
        recovery_window_end=r["recovery_window_end"],
        pushes=[BasebackupPushSummary(**p) for p in pushes_raw],
    )


async def _seed_pushes_for_basebackup(basebackup_id: UUID) -> None:
    """Create one pitr_basebackup_pushes row per remote in pitr_config_remotes."""
    remotes = await fetch_all(
        "SELECT remote_connection_id FROM pitr_config_remotes WHERE config_id = 1"
    )
    for r in remotes:
        await execute(
            "INSERT INTO pitr_basebackup_pushes (basebackup_id, remote_connection_id, status) "
            "VALUES ($1, $2, 'pending') "
            "ON CONFLICT (basebackup_id, remote_connection_id) DO NOTHING",
            basebackup_id,
            r["remote_connection_id"],
        )


# ---------------------------------------------------------------------------
# Stanza initialisation
# ---------------------------------------------------------------------------


async def ensure_stanza() -> None:
    """Idempotent stanza initialization.

    Called from `main.py` lifespan at backend startup. If the stanza already
    exists (per `pgbackrest info --output=json`), no-op. Otherwise create it.
    Raises RuntimeError if creation fails.
    """
    code, stdout, _ = await _pg_exec(["--stanza=" + STANZA, "info", "--output=json"])
    if code == 0 and stdout.strip():
        try:
            info = json.loads(stdout)
            if isinstance(info, list) and any(s.get("name") == STANZA for s in info):
                log.info("pitr.stanza.already_exists", stanza=STANZA)
                return
        except json.JSONDecodeError:
            log.warning("pitr.stanza.info_unparseable", stdout=stdout[:200])

    log.info("pitr.stanza.creating", stanza=STANZA)
    code, _, err = await _pg_exec(["--stanza=" + STANZA, "stanza-create"])
    if code != 0:
        raise RuntimeError(f"pgbackrest stanza-create failed: {err}")
    log.info("pitr.stanza.created", stanza=STANZA)


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------


async def list_basebackups() -> list[BasebackupSummary]:
    """All basebackups with their push entries aggregated."""
    rows = await fetch_all(
        """
        SELECT b.id, b.pgbackrest_label, b.started_at, b.completed_at,
               b.size_bytes, b.status, b.error,
               b.recovery_window_start, b.recovery_window_end,
               coalesce(
                   json_agg(
                       json_build_object(
                           'remote_connection_id', p.remote_connection_id,
                           'remote_connection_name', r.name,
                           'status', p.status,
                           'pushed_at', p.pushed_at,
                           'error', p.error,
                           'size_bytes', p.size_bytes
                       )
                   ) FILTER (WHERE p.id IS NOT NULL),
                   '[]'::json
               ) AS pushes
        FROM pitr_basebackups b
        LEFT JOIN pitr_basebackup_pushes p ON p.basebackup_id = b.id
        LEFT JOIN remote_backup_connections r ON r.id = p.remote_connection_id
        GROUP BY b.id
        ORDER BY b.started_at DESC
        """
    )
    return [_row_to_basebackup_summary(r) for r in rows]


async def get_basebackup(basebackup_id: UUID) -> BasebackupSummary:
    """Fetch a single basebackup by UUID. Raises BasebackupNotFoundError if absent."""
    for b in await list_basebackups():
        if b.id == basebackup_id:
            return b
    raise BasebackupNotFoundError(str(basebackup_id))


# ---------------------------------------------------------------------------
# Trigger
# ---------------------------------------------------------------------------


async def trigger_basebackup_now(*, actor_user_id: UUID | None = None) -> UUID:
    """Trigger a fresh pgbackrest full backup. Returns the inserted basebackup UUID."""
    running = await fetch_one(
        "SELECT id FROM pitr_basebackups WHERE status = 'running' LIMIT 1"
    )
    if running:
        raise BasebackupRunningError(str(running["id"]))

    placeholder_label = f"pending-{datetime.now(UTC).isoformat()}"
    row = await fetch_one(
        "INSERT INTO pitr_basebackups (pgbackrest_label, started_at, status) "
        "VALUES ($1, now(), 'running') RETURNING id",
        placeholder_label,
    )
    if row is None:
        raise RuntimeError("INSERT pitr_basebackups returned no row")
    bid: UUID = row["id"]

    log.info(
        "pitr.basebackup.started",
        basebackup_id=str(bid),
        actor_user_id=str(actor_user_id) if actor_user_id else None,
    )

    try:
        await ensure_stanza()
        code, stdout, err = await _pg_exec(
            ["--stanza=" + STANZA, "backup", "--type=full"]
        )
        if code != 0:
            raise RuntimeError(f"pgbackrest backup failed: {err}")

        match = _LABEL_RE.search(stdout)
        if match:
            label = match.group(1)
        else:
            label = await _last_label_from_info()
        size_bytes = await _label_size_from_info(label)

        await execute(
            "UPDATE pitr_basebackups SET pgbackrest_label = $2, status = 'ok', "
            "completed_at = now(), size_bytes = $3 WHERE id = $1",
            bid,
            label,
            size_bytes,
        )
        log.info(
            "pitr.basebackup.completed",
            basebackup_id=str(bid),
            label=label,
            size_bytes=size_bytes,
        )
    except Exception as exc:
        await execute(
            "UPDATE pitr_basebackups SET status = 'failed', completed_at = now(), "
            "error = $2 WHERE id = $1",
            bid,
            str(exc),
        )
        log.error("pitr.basebackup.failed", basebackup_id=str(bid), error=str(exc))
        raise

    await _seed_pushes_for_basebackup(bid)
    return bid


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


async def delete_basebackup(basebackup_id: UUID) -> None:
    """Delete a basebackup row. Refuses if it's the only OK one remaining.

    Pushes are deleted first because the FK on pitr_basebackup_pushes.basebackup_id
    is RESTRICT (not CASCADE). The caller (API) may also delete pushes beforehand
    if needed; the DELETE below is idempotent if pushes are already gone.
    """
    bb = await fetch_one(
        "SELECT id, pgbackrest_label FROM pitr_basebackups "
        "WHERE id = $1 AND status = 'ok'",
        basebackup_id,
    )
    if bb is None:
        raise BasebackupNotFoundError(str(basebackup_id))

    count_row = await fetch_one(
        "SELECT count(*)::int AS n FROM pitr_basebackups WHERE status = 'ok'"
    )
    if count_row is None or count_row["n"] <= 1:
        raise BasebackupIsLastError(str(basebackup_id))

    # Remove dependent pushes first (FK is RESTRICT — not CASCADE)
    await execute(
        "DELETE FROM pitr_basebackup_pushes WHERE basebackup_id = $1",
        basebackup_id,
    )

    code, _, err = await _pg_exec(
        ["--stanza=" + STANZA, "expire", f"--set={bb['pgbackrest_label']}"]
    )
    if code != 0:
        raise RuntimeError(f"pgbackrest expire failed: {err}")

    await execute("DELETE FROM pitr_basebackups WHERE id = $1", basebackup_id)
    log.info(
        "pitr.basebackup.deleted",
        basebackup_id=str(basebackup_id),
        label=bb["pgbackrest_label"],
    )
