from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agflow.services.remote_backup_providers import RemoteBackupProviderError

# ─── SFTP ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sftp_test_connection_success():
    from agflow.services.remote_backup_providers.sftp_provider import SftpProvider

    mock_sftp = AsyncMock()
    mock_sftp.stat = AsyncMock(return_value=MagicMock())

    mock_conn = MagicMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)

    mock_sftp_ctx = MagicMock()
    mock_sftp_ctx.__aenter__ = AsyncMock(return_value=mock_sftp)
    mock_sftp_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_conn.start_sftp_client = MagicMock(return_value=mock_sftp_ctx)

    config = {"host": "sftp.example.com", "port": 22}
    creds = {"username": "user", "auth_method": "password", "password": "secret"}
    provider = SftpProvider(config=config, credentials=creds)

    with patch("asyncssh.connect", AsyncMock(return_value=mock_conn)):
        await provider.test_connection("/backups")

    mock_sftp.stat.assert_called_once()


@pytest.mark.asyncio
async def test_sftp_upload_stream_creates_parent_dirs():
    from agflow.services.remote_backup_providers.sftp_provider import SftpProvider

    mock_sftp = AsyncMock()
    mock_sftp.stat = AsyncMock(side_effect=OSError("not found"))
    mock_sftp.makedirs = AsyncMock()
    mock_sftp.realpath = AsyncMock(return_value="/")

    mock_file = MagicMock()
    mock_file.__aenter__ = AsyncMock(return_value=mock_file)
    mock_file.__aexit__ = AsyncMock(return_value=False)
    mock_file.write = AsyncMock()
    mock_sftp.open = AsyncMock(return_value=mock_file)

    mock_conn = MagicMock()
    mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_conn.__aexit__ = AsyncMock(return_value=False)
    mock_sftp_ctx = MagicMock()
    mock_sftp_ctx.__aenter__ = AsyncMock(return_value=mock_sftp)
    mock_sftp_ctx.__aexit__ = AsyncMock(return_value=False)
    mock_conn.start_sftp_client = MagicMock(return_value=mock_sftp_ctx)

    async def _source():
        yield b"chunk1"
        yield b"chunk2"

    config = {"host": "sftp.example.com", "port": 22}
    creds = {"username": "user", "auth_method": "password", "password": "s"}
    provider = SftpProvider(config=config, credentials=creds)

    with patch("asyncssh.connect", AsyncMock(return_value=mock_conn)):
        n = await provider.upload_stream("/backups", "dump.sql.gz", _source())

    assert n == len(b"chunk1") + len(b"chunk2")
    mock_sftp.makedirs.assert_called_once_with("/backups", exist_ok=True)


# ─── FTPS ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ftps_upload_stream_success():
    from agflow.services.remote_backup_providers.ftps_provider import FtpsProvider

    async def _drain_and_upload(gen, path):
        """Consume the generator so the written counter is updated."""
        async for _ in gen:
            pass

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.login = AsyncMock()
    mock_client.upload_stream = AsyncMock(side_effect=_drain_and_upload)
    mock_client.make_directory = AsyncMock()

    async def _source():
        yield b"data"

    config = {"host": "ftp.example.com", "port": 21, "use_tls": True}
    creds = {"username": "user", "password": "pass"}
    provider = FtpsProvider(config=config, credentials=creds)

    with patch("aioftp.Client.context", return_value=mock_client):
        n = await provider.upload_stream("/backups", "dump.sql.gz", _source())

    mock_client.upload_stream.assert_called_once()
    assert n == len(b"data")


# ─── S3 ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_s3_upload_creates_temp_file_and_cleans_up():
    from agflow.services.remote_backup_providers.s3_provider import S3CompatibleProvider

    mock_s3 = MagicMock()
    mock_s3.upload_fileobj = MagicMock()

    async def _source():
        yield b"s3data"

    config = {
        "endpoint_url": "https://s3.fr-par.scw.cloud",
        "region": "fr-par",
        "bucket": "my-bucket",
    }
    creds = {"access_key_id": "AK", "secret_access_key": "SK"}
    provider = S3CompatibleProvider(config=config, credentials=creds)

    with patch("boto3.client", return_value=mock_s3):
        n = await provider.upload_stream("snapshots/", "dump.sql.gz", _source())

    mock_s3.upload_fileobj.assert_called_once()
    assert n == len(b"s3data")


# ─── Validation filename ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sftp_rejects_filename_with_slash():
    from agflow.services.remote_backup_providers.sftp_provider import SftpProvider

    async def _source():
        yield b"data"

    provider = SftpProvider(config={"host": "h", "port": 22}, credentials={"username": "u"})
    with pytest.raises(RemoteBackupProviderError):
        await provider.upload_stream("/backups", "path/to/dump.gz", _source())


# ─── Factory dispatch ───────────────────────────────────────────────────────

def test_factory_returns_correct_provider():
    from agflow.services.remote_backup_providers.factory import get_provider
    from agflow.services.remote_backup_providers.ftps_provider import FtpsProvider
    from agflow.services.remote_backup_providers.s3_provider import S3CompatibleProvider
    from agflow.services.remote_backup_providers.sftp_provider import SftpProvider

    assert isinstance(
        get_provider("sftp", {"host": "h", "port": 22}, {"username": "u"}),
        SftpProvider,
    )
    assert isinstance(
        get_provider("ftps", {"host": "h"}, {"username": "u", "password": "p"}),
        FtpsProvider,
    )
    assert isinstance(
        get_provider("s3", {"bucket": "b"}, {"access_key_id": "k", "secret_access_key": "s"}),
        S3CompatibleProvider,
    )
    with pytest.raises(RemoteBackupProviderError):
        get_provider("unknown", {}, {})
