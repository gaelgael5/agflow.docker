"""WAL archive monitoring + recovery window refresh."""
from __future__ import annotations

import json
from datetime import UTC, datetime

import structlog

from agflow.db.pool import fetch_one
from agflow.docker.exec_helper import docker_exec
from agflow.schemas.pitr import WalStatus
from agflow.services.pitr_basebackup_service import POSTGRES_CONTAINER, STANZA

log = structlog.get_logger(__name__)


async def _pg_exec(args: list[str]) -> tuple[int, str, str]:
    """Run a command inside the agflow-postgres container (NOT prefixed with pgbackrest)."""
    return await docker_exec(POSTGRES_CONTAINER, args)


async def _archive_mode_on() -> bool:
    """SELECT pg_settings WHERE name='archive_mode'."""
    row = await fetch_one(
        "SELECT setting FROM pg_settings WHERE name = 'archive_mode'"
    )
    return bool(row) and row["setting"] == "on"


async def _last_archived_at() -> datetime | None:
    """Read the mtime of the most recent WAL archive file in the pgbackrest repo.

    Uses `pgbackrest info --output=json` to find the max WAL filename, then
    `stat -c %Y` to get its mtime (epoch seconds). Returns None on any error.
    """
    code, info_out, _ = await _pg_exec(
        ["pgbackrest", "--stanza=" + STANZA, "info", "--output=json"]
    )
    if code != 0 or not info_out.strip():
        return None
    try:
        info = json.loads(info_out)
    except json.JSONDecodeError:
        log.warning("pitr.wal.info_unparseable", stdout=info_out[:200])
        return None
    archives = info[0].get("archive", []) if info else []
    if not archives:
        return None
    last_max = archives[-1].get("max")
    if not last_max:
        return None
    # Stat the WAL file in the repo. The .gz extension comes from compression=zst,
    # but pgbackrest may use .zst — try a glob via shell.
    code, ts_out, _ = await _pg_exec([
        "sh", "-c",
        f"stat -c %Y /var/lib/pgbackrest/archive/{STANZA}/*/{last_max}* 2>/dev/null | tail -n 1",
    ])
    ts_str = ts_out.strip()
    if code != 0 or not ts_str.isdigit():
        return None
    return datetime.fromtimestamp(int(ts_str), tz=UTC)


def _parse_df_output(df_out: str) -> tuple[int, int]:
    """Parse `df -B 1` output. Returns (used_bytes, free_bytes), or (0, 0) on parse failure."""
    lines = df_out.strip().splitlines()
    if len(lines) < 2:
        return 0, 0
    parts = lines[1].split()
    if len(parts) < 4:
        return 0, 0
    try:
        return int(parts[2]), int(parts[3])
    except ValueError:
        return 0, 0


async def get_wal_status() -> WalStatus:
    """Aggregate WAL archiving status, last archived timestamp, and disk usage."""
    archiving = await _archive_mode_on()
    last_at = await _last_archived_at()
    lag_s = (
        int((datetime.now(UTC) - last_at).total_seconds())
        if last_at is not None
        else None
    )
    code, df_out, _ = await _pg_exec(["df", "-B", "1", "/var/lib/pgbackrest"])
    used, free = _parse_df_output(df_out) if code == 0 else (0, 0)

    return WalStatus(
        archiving_enabled=archiving,
        last_archived_at=last_at,
        archive_lag_seconds=lag_s,
        wal_disk_used_bytes=used,
        wal_disk_free_bytes=free,
    )


async def refresh_recovery_windows() -> int:
    """Update recovery_window_end = now() for all status='ok' basebackups.

    The WAL archive is continuous up to "now", so all OK basebackups share the
    same recovery window upper bound. Called from `pitr_scheduler` every 5min.
    Returns count of rows updated.
    """
    code, info_out, _ = await _pg_exec(
        ["pgbackrest", "--stanza=" + STANZA, "info", "--output=json"]
    )
    if code != 0 or not info_out.strip():
        log.warning("pitr.wal.refresh_skipped_no_info", code=code)
        return 0

    now_utc = datetime.now(UTC)
    result = await fetch_one(
        "WITH updated AS ("
        "  UPDATE pitr_basebackups SET recovery_window_end = $1 "
        "  WHERE status = 'ok' RETURNING id"
        ") SELECT count(*)::int AS n FROM updated",
        now_utc,
    )
    n = int(result["n"]) if result else 0
    if n > 0:
        log.info("pitr.wal.recovery_window_refreshed", count=n, end=now_utc.isoformat())
    return n
