from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

import structlog

from agflow.db.pool import fetch_one
from agflow.schemas.remote_backup_files import RestoreResult
from agflow.services import db_backup
from agflow.services.backup_lock import backup_lock

_log = structlog.get_logger(__name__)
_CHUNK = 64 * 1024


async def _stream_file(path: Path) -> AsyncIterator[bytes]:
    f = await asyncio.to_thread(path.open, "rb")
    try:
        while True:
            chunk = await asyncio.to_thread(f.read, _CHUNK)
            if not chunk:
                return
            yield chunk
    finally:
        await asyncio.to_thread(f.close)


async def restore_local_backup(backup_id: UUID) -> RestoreResult:
    """Restore destructif d'un local_backup dans Postgres (DROP + recreate).

    Sérialisé via backup_lock pour exclure les opérations concurrentes (dump/pull).
    """
    async with backup_lock:
        row = await fetch_one(
            "SELECT filename, file_path, status FROM local_backups WHERE id = $1",
            backup_id,
        )
        if row is None:
            raise ValueError(f"Backup {backup_id} not found")
        if row["status"] != "completed":
            raise ValueError(
                f"Backup status is {row['status']!r}, must be 'completed'"
            )

        path = Path(row["file_path"])
        if not path.exists():
            raise FileNotFoundError(f"Backup file missing: {path}")

        _log.info("restore.start", id=str(backup_id), filename=row["filename"])
        result = await db_backup.restore_dump(_stream_file(path))
        exit_code = int(result.get("exit_code", -1))
        tail = str(result.get("tail", ""))

        if exit_code != 0:
            _log.warning(
                "restore.failed",
                id=str(backup_id),
                exit_code=exit_code,
                tail=tail,
            )
            raise RuntimeError(
                f"Restore failed with exit code {exit_code}. Output tail: {tail}"
            )

        _log.info("restore.success", id=str(backup_id), exit_code=exit_code)
        return RestoreResult(
            backup_id=backup_id, exit_code=exit_code, output_tail=tail
        )
