from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agflow.services.remote_backup_providers.protocol import (
    RemoteBackupProvider,
    RemoteBackupProviderError,
    RemoteFile,
)
from agflow.services.remote_backup_providers.sftp_provider import SftpProvider


def test_remote_file_dataclass_fields():
    """RemoteFile exposes filename, size_bytes, last_modified."""
    rf = RemoteFile(filename="x.sql.gz", size_bytes=1024, last_modified=datetime(2026, 5, 1))
    assert rf.filename == "x.sql.gz"
    assert rf.size_bytes == 1024
    assert rf.last_modified == datetime(2026, 5, 1)


def test_protocol_has_list_remote_and_download_stream():
    """The Protocol exposes the new methods."""
    assert hasattr(RemoteBackupProvider, "list_remote")
    assert hasattr(RemoteBackupProvider, "download_stream")


def _sftp_provider() -> SftpProvider:
    return SftpProvider(
        config={"host": "h", "port": 22},
        credentials={"username": "u", "password": "p"},
    )


@pytest.mark.asyncio
async def test_sftp_list_remote_returns_files():
    """list_remote returns only files (not subdirs, not . / ..)."""
    provider = _sftp_provider()

    file_attrs = MagicMock(size=1024, mtime=1714521600)
    dir_attrs = MagicMock(size=0, mtime=1714521600)
    sftp = AsyncMock()
    sftp.readdir = AsyncMock(
        return_value=[
            MagicMock(filename="backup.sql.gz", attrs=file_attrs),
            MagicMock(filename="subdir", attrs=dir_attrs),
            MagicMock(filename=".", attrs=dir_attrs),
            MagicMock(filename="..", attrs=dir_attrs),
        ]
    )
    sftp.isfile = AsyncMock(side_effect=lambda p: p.endswith("backup.sql.gz"))

    sftp_ctx = MagicMock()
    sftp_ctx.__aenter__ = AsyncMock(return_value=sftp)
    sftp_ctx.__aexit__ = AsyncMock(return_value=False)

    conn = MagicMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    conn.start_sftp_client = MagicMock(return_value=sftp_ctx)

    with patch(
        "agflow.services.remote_backup_providers.sftp_provider.asyncssh.connect",
        AsyncMock(return_value=conn),
    ):
        files = await provider.list_remote("/backups")

    assert len(files) == 1
    assert files[0].filename == "backup.sql.gz"
    assert files[0].size_bytes == 1024
    # mtime=1714521600 → 2024-05-01 00:00:00 UTC
    assert files[0].last_modified == datetime(2024, 5, 1, 0, 0, 0, tzinfo=UTC)
    assert files[0].last_modified.tzinfo is UTC


@pytest.mark.asyncio
async def test_sftp_list_remote_raises_on_error():
    """On SFTP error, list_remote raises RemoteBackupProviderError."""
    provider = _sftp_provider()
    with (
        patch(
            "agflow.services.remote_backup_providers.sftp_provider.asyncssh.connect",
            side_effect=OSError("connection refused"),
        ),
        pytest.raises(RemoteBackupProviderError, match="SFTP list failed"),
    ):
        await provider.list_remote("/backups")


@pytest.mark.asyncio
async def test_sftp_download_stream_rejects_path_separator():
    """download_stream rejects filenames containing path separators."""
    provider = _sftp_provider()
    with pytest.raises(RemoteBackupProviderError, match="path separators"):
        async for _ in await provider.download_stream("/p", "evil/../escape"):
            pass


@pytest.mark.asyncio
async def test_sftp_download_stream_yields_chunks():
    """download_stream reads the file in 64KB chunks until EOF."""
    provider = _sftp_provider()

    chunks = [b"chunk1", b"chunk2", b""]  # b"" = EOF
    remote_file = MagicMock()
    remote_file.__aenter__ = AsyncMock(return_value=remote_file)
    remote_file.__aexit__ = AsyncMock(return_value=False)
    remote_file.read = AsyncMock(side_effect=chunks)

    sftp = AsyncMock()
    sftp.open = AsyncMock(return_value=remote_file)

    sftp_ctx = MagicMock()
    sftp_ctx.__aenter__ = AsyncMock(return_value=sftp)
    sftp_ctx.__aexit__ = AsyncMock(return_value=False)

    conn = MagicMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    conn.start_sftp_client = MagicMock(return_value=sftp_ctx)

    with patch(
        "agflow.services.remote_backup_providers.sftp_provider.asyncssh.connect",
        AsyncMock(return_value=conn),
    ):
        result_chunks = []
        async for c in await provider.download_stream("/backups", "backup.sql.gz"):
            result_chunks.append(c)

    assert result_chunks == [b"chunk1", b"chunk2"]
