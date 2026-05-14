from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest

from agflow.services import restore_service


@pytest.mark.asyncio
async def test_restore_local_backup_pipes_to_db_backup_restore_dump(tmp_path: Path):
    """restore_local_backup ouvre le fichier et le passe à db_backup.restore_dump."""
    backup_id = uuid4()
    file_path = tmp_path / "x.sql.gz"
    file_path.write_bytes(b"gzipped sql content")

    captured: list[bytes] = []

    async def _fake_restore(stream):
        async for chunk in stream:
            captured.append(chunk)
        return {"exit_code": 0, "tail": "DONE"}

    with (
        patch("agflow.services.restore_service.fetch_one") as mock_fetch,
        patch("agflow.services.restore_service.db_backup") as mock_db,
    ):
        mock_fetch.return_value = {
            "filename": "x.sql.gz",
            "file_path": str(file_path),
            "status": "completed",
        }
        mock_db.restore_dump = _fake_restore

        result = await restore_service.restore_local_backup(backup_id)

    assert result.exit_code == 0
    assert result.output_tail == "DONE"
    assert b"".join(captured) == b"gzipped sql content"


@pytest.mark.asyncio
async def test_restore_local_backup_raises_if_backup_not_completed():
    """Si status != 'completed', ValueError."""
    with patch("agflow.services.restore_service.fetch_one") as mock_fetch:
        mock_fetch.return_value = {
            "filename": "x.sql.gz",
            "file_path": "/tmp/x",
            "status": "failed",
        }
        with pytest.raises(ValueError, match="completed"):
            await restore_service.restore_local_backup(uuid4())


@pytest.mark.asyncio
async def test_restore_local_backup_raises_if_file_missing(tmp_path: Path):
    """Si le fichier sur disque a été supprimé, FileNotFoundError."""
    with patch("agflow.services.restore_service.fetch_one") as mock_fetch:
        mock_fetch.return_value = {
            "filename": "x.sql.gz",
            "file_path": str(tmp_path / "does-not-exist.sql.gz"),
            "status": "completed",
        }
        with pytest.raises(FileNotFoundError, match="missing"):
            await restore_service.restore_local_backup(uuid4())


@pytest.mark.asyncio
async def test_restore_local_backup_raises_on_nonzero_exit(tmp_path: Path):
    """Si pg_restore exit != 0, RuntimeError."""
    file_path = tmp_path / "x.sql.gz"
    file_path.write_bytes(b"corrupted")

    async def _failing_restore(stream):
        async for _ in stream:
            pass
        return {"exit_code": 3, "tail": "ERROR: syntax"}

    with (
        patch("agflow.services.restore_service.fetch_one") as mock_fetch,
        patch("agflow.services.restore_service.db_backup") as mock_db,
    ):
        mock_fetch.return_value = {
            "filename": "x.sql.gz",
            "file_path": str(file_path),
            "status": "completed",
        }
        mock_db.restore_dump = _failing_restore

        with pytest.raises(RuntimeError, match="exit code 3"):
            await restore_service.restore_local_backup(uuid4())


@pytest.mark.asyncio
async def test_restore_local_backup_acquires_lock():
    """L'opération acquiert backup_lock pour exclure les autres jobs."""
    from agflow.services.backup_lock import backup_lock

    with patch("agflow.services.restore_service.fetch_one") as mock_fetch:
        mock_fetch.return_value = None  # → not found après acquisition du lock

        await backup_lock.acquire()
        try:
            task = asyncio.create_task(restore_service.restore_local_backup(uuid4()))
            await asyncio.sleep(0.05)
            assert not task.done(), "should be waiting on backup_lock"
            backup_lock.release()
            with pytest.raises(ValueError):
                await task
        finally:
            if backup_lock.locked():
                backup_lock.release()
