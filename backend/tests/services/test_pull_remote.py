from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from agflow.services import local_backups_service as svc
from agflow.services.remote_backup_providers.protocol import RemoteBackupProviderError


async def _async_iter(items: list[bytes]):
    for it in items:
        yield it


@pytest.mark.asyncio
async def test_pull_remote_to_local_creates_local_backup(tmp_path: Path):
    """pull_remote_to_local streams the file, persists it, inserts a local_backup row."""
    remote_id, user_id = uuid4(), uuid4()
    chunks = [b"hello ", b"world!"]

    provider = MagicMock()
    provider.download_stream = AsyncMock(return_value=_async_iter(chunks))

    with (
        patch.object(svc, "_backups_dir", return_value=tmp_path),
        patch("agflow.services.local_backups_service.get_provider", return_value=provider),
        patch("agflow.services.local_backups_service.rbc_service") as mock_rbc,
        patch("agflow.services.local_backups_service.execute") as mock_exec,
        patch("agflow.services.local_backups_service.fetch_one") as mock_fetch,
    ):
        mock_rbc.get_connection = AsyncMock(
            return_value=MagicMock(
                id=remote_id,
                kind="sftp",
                config={"remote_path_full": "/backups"},
                has_credentials=True,
            )
        )
        mock_rbc.fetch_credentials = AsyncMock(return_value={"username": "u", "password": "p"})
        mock_rbc.resolve_remote_path = MagicMock(return_value="/backups")
        # Final SELECT for the DTO (after pull completes)
        mock_fetch.return_value = {
            "id": uuid4(),
            "filename": "x.sql.gz",
            "size_bytes": 12,
            "status": "completed",
            "created_at": datetime(2026, 5, 14, 12, 0, 0, tzinfo=UTC),
            "source_remote_connection_id": remote_id,
        }

        result = await svc.pull_remote_to_local(
            remote_id,
            filename="x.sql.gz",
            created_by_user_id=user_id,
        )

    # 1. download_stream called with the right path/filename
    provider.download_stream.assert_called_once_with("/backups", "x.sql.gz")
    # 2. Two execute calls: INSERT then UPDATE status='completed'
    assert mock_exec.await_count == 2
    insert_sql = mock_exec.await_args_list[0].args[0]
    assert "INSERT INTO local_backups" in insert_sql
    assert "source_remote_connection_id" in insert_sql
    # 3. File written with the joined chunks
    files = list(tmp_path.iterdir())
    assert len(files) == 1
    assert files[0].read_bytes() == b"hello world!"
    # 4. DTO exposes source_remote_connection_id
    assert result.source_remote_connection_id == remote_id


@pytest.mark.asyncio
async def test_pull_remote_to_local_rolls_back_on_provider_error(tmp_path: Path):
    """If the provider raises mid-stream, the partial file is deleted and the row is 'failed'."""
    remote_id = uuid4()

    provider = MagicMock()

    async def _failing_iter():
        yield b"partial"
        raise RemoteBackupProviderError("network down")

    provider.download_stream = AsyncMock(return_value=_failing_iter())

    with (
        patch.object(svc, "_backups_dir", return_value=tmp_path),
        patch("agflow.services.local_backups_service.get_provider", return_value=provider),
        patch("agflow.services.local_backups_service.rbc_service") as mock_rbc,
        patch("agflow.services.local_backups_service.execute") as mock_exec,
    ):
        mock_rbc.get_connection = AsyncMock(
            return_value=MagicMock(
                id=remote_id,
                kind="sftp",
                config={"remote_path_full": "/backups"},
                has_credentials=True,
            )
        )
        mock_rbc.fetch_credentials = AsyncMock(return_value={"username": "u", "password": "p"})
        mock_rbc.resolve_remote_path = MagicMock(return_value="/backups")

        with pytest.raises(RuntimeError, match="Pull failed"):
            await svc.pull_remote_to_local(remote_id, filename="x.sql.gz")

    # File deleted
    assert list(tmp_path.iterdir()) == []
    # Last UPDATE marked status='failed'
    failed_calls = [
        call for call in mock_exec.await_args_list if "status='failed'" in (call.args[0] or "")
    ]
    assert len(failed_calls) >= 1


@pytest.mark.asyncio
async def test_pull_remote_to_local_missing_connection_raises():
    """ValueError if the remote connection doesn't exist."""
    with patch("agflow.services.local_backups_service.rbc_service") as mock_rbc:
        mock_rbc.get_connection = AsyncMock(return_value=None)
        with pytest.raises(ValueError, match="not found"):
            await svc.pull_remote_to_local(uuid4(), filename="x.sql.gz")


@pytest.mark.asyncio
async def test_pull_remote_to_local_no_credentials_raises():
    """ValueError if fetch_credentials returns None."""
    with patch("agflow.services.local_backups_service.rbc_service") as mock_rbc:
        mock_rbc.get_connection = AsyncMock(
            return_value=MagicMock(
                id=uuid4(),
                kind="sftp",
                config={},
                has_credentials=False,
            )
        )
        mock_rbc.fetch_credentials = AsyncMock(return_value=None)
        mock_rbc.resolve_remote_path = MagicMock(return_value="/backups")
        with pytest.raises(ValueError, match="credentials"):
            await svc.pull_remote_to_local(uuid4(), filename="x.sql.gz")
