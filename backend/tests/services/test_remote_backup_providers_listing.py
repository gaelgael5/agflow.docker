from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agflow.services.remote_backup_providers.ftps_provider import FtpsProvider
from agflow.services.remote_backup_providers.protocol import (
    RemoteBackupProvider,
    RemoteBackupProviderError,
    RemoteFile,
)
from agflow.services.remote_backup_providers.s3_provider import S3CompatibleProvider
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


# ─── FTPS ──────────────────────────────────────────────────────────────────


def _ftps_provider() -> FtpsProvider:
    return FtpsProvider(
        config={"host": "h", "port": 21, "use_tls": False},
        credentials={"username": "u", "password": "p"},
    )


async def _async_iter(items: list[bytes]):
    for it in items:
        yield it


@pytest.mark.asyncio
async def test_ftps_list_remote_filters_directories():
    """list_remote returns only files (type='file'), not dirs."""
    provider = _ftps_provider()

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.login = AsyncMock()
    mock_client.list = AsyncMock(
        return_value=[
            (
                MagicMock(parts=["/backups", "x.sql.gz"]),
                {"type": "file", "size": "2048", "modify": "20260101000000"},
            ),
            (
                MagicMock(parts=["/backups", "subdir"]),
                {"type": "dir", "size": "0"},
            ),
        ]
    )

    with patch("aioftp.Client.context", return_value=mock_client):
        files = await provider.list_remote("/backups")

    assert len(files) == 1
    assert files[0].filename == "x.sql.gz"
    assert files[0].size_bytes == 2048


@pytest.mark.asyncio
async def test_ftps_list_remote_raises_on_error():
    """Connection error → RemoteBackupProviderError('FTPS list failed')."""
    provider = _ftps_provider()
    with (
        patch(
            "aioftp.Client.context",
            side_effect=ConnectionError("nope"),
        ),
        pytest.raises(RemoteBackupProviderError, match="FTPS list failed"),
    ):
        await provider.list_remote("/backups")


@pytest.mark.asyncio
async def test_ftps_download_stream_rejects_path_separator():
    """Filename safety check fires before iteration."""
    provider = _ftps_provider()
    with pytest.raises(RemoteBackupProviderError, match="path separators"):
        async for _ in await provider.download_stream("/p", "evil/escape"):
            pass


@pytest.mark.asyncio
async def test_ftps_download_stream_yields_chunks():
    """download_stream yields the chunks returned by aioftp.iter_by_block."""
    provider = _ftps_provider()

    stream = MagicMock()
    stream.__aenter__ = AsyncMock(return_value=stream)
    stream.__aexit__ = AsyncMock(return_value=False)
    stream.iter_by_block = MagicMock(return_value=_async_iter([b"data1", b"data2"]))

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.login = AsyncMock()
    mock_client.download_stream = MagicMock(return_value=stream)

    with patch("aioftp.Client.context", return_value=mock_client):
        result = []
        async for c in await provider.download_stream("/backups", "x.sql.gz"):
            result.append(c)

    assert result == [b"data1", b"data2"]


# ─── S3 ────────────────────────────────────────────────────────────────────


def _s3_provider() -> S3CompatibleProvider:
    return S3CompatibleProvider(
        config={"bucket": "b", "region": "us-east-1"},
        credentials={"access_key_id": "k", "secret_access_key": "s"},
    )


@pytest.mark.asyncio
async def test_s3_list_remote_returns_objects():
    """list_remote returns objects under the prefix, skipping the dir marker."""
    provider = _s3_provider()

    client = MagicMock()
    client.list_objects_v2.return_value = {
        "Contents": [
            {
                "Key": "backups/x.sql.gz",
                "Size": 4096,
                "LastModified": datetime(2026, 5, 1, tzinfo=UTC),
            },
            {
                "Key": "backups/y.sql.gz",
                "Size": 8192,
                "LastModified": datetime(2026, 5, 2, tzinfo=UTC),
            },
            {"Key": "backups/", "Size": 0, "LastModified": datetime(2026, 5, 1, tzinfo=UTC)},
        ]
    }

    with patch.object(provider, "_client", return_value=client):
        files = await provider.list_remote("backups")

    assert sorted(f.filename for f in files) == ["x.sql.gz", "y.sql.gz"]


@pytest.mark.asyncio
async def test_s3_list_remote_empty_bucket():
    """list_remote returns [] when no Contents key in the response."""
    provider = _s3_provider()
    client = MagicMock()
    client.list_objects_v2.return_value = {}

    with patch.object(provider, "_client", return_value=client):
        files = await provider.list_remote("backups")

    assert files == []


@pytest.mark.asyncio
async def test_s3_list_remote_raises_on_error():
    """boto3 error → RemoteBackupProviderError."""
    provider = _s3_provider()
    client = MagicMock()
    client.list_objects_v2.side_effect = RuntimeError("NoSuchBucket")

    with (
        patch.object(provider, "_client", return_value=client),
        pytest.raises(RemoteBackupProviderError, match="S3 list failed"),
    ):
        await provider.list_remote("backups")


@pytest.mark.asyncio
async def test_s3_download_stream_yields_chunks():
    """download_stream reads Body of get_object in 64KB chunks."""
    provider = _s3_provider()

    body = MagicMock()
    body.read.side_effect = [b"chunk1", b"chunk2", b""]  # b"" = EOF

    client = MagicMock()
    client.get_object.return_value = {"Body": body}

    with patch.object(provider, "_client", return_value=client):
        result = []
        async for c in await provider.download_stream("backups", "x.sql.gz"):
            result.append(c)

    assert result == [b"chunk1", b"chunk2"]


@pytest.mark.asyncio
async def test_s3_download_stream_rejects_path_separator():
    """Filename safety check fires before iteration."""
    provider = _s3_provider()
    with pytest.raises(RemoteBackupProviderError, match="path separators"):
        async for _ in await provider.download_stream("backups", "evil/escape"):
            pass
