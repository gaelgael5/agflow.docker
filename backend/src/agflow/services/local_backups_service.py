from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID, uuid4

import structlog

from agflow.config import get_settings
from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.schemas.local_backups import LocalBackupSummary
from agflow.services import db_backup
from agflow.services.backup_lock import backup_lock

_log = structlog.get_logger(__name__)


def _backups_dir() -> Path:
    settings = get_settings()
    d = Path(settings.agflow_data_dir) / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _to_dto(row: dict) -> LocalBackupSummary:
    return LocalBackupSummary(
        id=row["id"],
        filename=row["filename"],
        size_bytes=row["size_bytes"],
        status=row["status"],
        created_at=row["created_at"],
    )


async def list_backups() -> list[LocalBackupSummary]:
    rows = await fetch_all(
        "SELECT id, filename, size_bytes, status, created_at "
        "FROM local_backups ORDER BY created_at DESC LIMIT 100"
    )
    return [_to_dto(r) for r in rows]


async def get_backup(backup_id: UUID) -> LocalBackupSummary | None:
    row = await fetch_one(
        "SELECT id, filename, size_bytes, status, created_at FROM local_backups WHERE id = $1",
        backup_id,
    )
    return _to_dto(row) if row else None


async def create_backup(created_by_user_id: UUID | None = None) -> LocalBackupSummary:
    """Stream pg_dump vers disque, enregistre en DB. Sérialise via backup_lock."""
    async with backup_lock:
        backup_id = uuid4()
        filename = db_backup.export_filename()
        file_path = _backups_dir() / filename

        await execute(
            "INSERT INTO local_backups (id, filename, file_path, status, created_by_user_id) "
            "VALUES ($1, $2, $3, 'in_progress', $4)",
            backup_id, filename, str(file_path), created_by_user_id,
        )
        try:
            written = 0
            with file_path.open("wb") as f:
                async for chunk in db_backup.stream_dump():
                    await asyncio.to_thread(f.write, chunk)
                    written += len(chunk)
            await execute(
                "UPDATE local_backups SET status='completed', size_bytes=$1 WHERE id=$2",
                written, backup_id,
            )
            _log.info("local_backup.created", id=str(backup_id), size=written)
        except Exception as exc:
            await execute("UPDATE local_backups SET status='failed' WHERE id=$1", backup_id)
            file_path.unlink(missing_ok=True)
            raise RuntimeError(f"Backup creation failed: {exc}") from exc

    row = await fetch_one(
        "SELECT id, filename, size_bytes, status, created_at FROM local_backups WHERE id=$1",
        backup_id,
    )
    return _to_dto(row)


async def stream_backup_chunks(backup_id: UUID):
    """AsyncIterator[bytes] depuis le fichier backup local."""
    row = await fetch_one("SELECT file_path, status FROM local_backups WHERE id=$1", backup_id)
    if row is None:
        raise FileNotFoundError(f"Backup {backup_id} not found")
    if row["status"] != "completed":
        raise ValueError(f"Backup {backup_id} has status={row['status']!r}")
    path = Path(row["file_path"])
    if not path.exists():
        raise FileNotFoundError(f"Backup file missing: {path}")

    async def _gen():
        f = await asyncio.to_thread(path.open, "rb")
        try:
            while True:
                chunk = await asyncio.to_thread(f.read, 64 * 1024)
                if not chunk:
                    return
                yield chunk
        finally:
            await asyncio.to_thread(f.close)

    return _gen()
