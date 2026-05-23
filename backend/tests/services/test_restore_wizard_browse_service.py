from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agflow.schemas.restore_wizard import RemoteEntry
from agflow.services.restore_wizard_browse_service import browse_remote


@pytest.mark.asyncio
async def test_browse_remote_sftp_returns_files_and_dirs():
    entry_dir = MagicMock()
    entry_dir.filename = "backups"
    entry_dir.attrs.permissions = 0o40755  # S_ISDIR
    entry_dir.attrs.size = None
    entry_dir.attrs.mtime = None

    entry_file = MagicMock()
    entry_file.filename = "dump.sql.gz"
    entry_file.attrs.permissions = 0o100644  # regular file
    entry_file.attrs.size = 1024
    entry_file.attrs.mtime = 1700000000

    dot = MagicMock()
    dot.filename = "."

    fake_sftp = AsyncMock()
    fake_sftp.readdir = AsyncMock(return_value=[dot, entry_dir, entry_file])
    fake_sftp.__aenter__ = AsyncMock(return_value=fake_sftp)
    fake_sftp.__aexit__ = AsyncMock(return_value=None)

    fake_conn = AsyncMock()
    fake_conn.__aenter__ = AsyncMock(return_value=fake_conn)
    fake_conn.__aexit__ = AsyncMock(return_value=None)
    fake_conn.start_sftp_client = MagicMock(return_value=fake_sftp)

    with patch("asyncssh.connect", return_value=fake_conn):
        entries = await browse_remote(
            connection_type="sftp",
            manual_fields={"host": "192.168.1.1", "port": "22", "path": "/backups"},
            credentials={"username": "root", "private_key": None, "password": "secret"},
        )

    # Dirs en premier, puis fichiers
    assert entries[0].name == "backups"
    assert entries[0].is_dir is True
    assert entries[1].name == "dump.sql.gz"
    assert entries[1].is_dir is False
    assert entries[1].size_bytes == 1024


@pytest.mark.asyncio
async def test_browse_remote_other_provider_flat_list():
    fake_files = [
        MagicMock(filename="dump.sql.gz", size_bytes=2048, last_modified=None),
    ]
    fake_provider = AsyncMock()
    fake_provider.list_remote = AsyncMock(return_value=fake_files)

    with patch(
        "agflow.services.restore_wizard_browse_service.get_provider",
        return_value=fake_provider,
    ):
        entries = await browse_remote(
            connection_type="s3",
            manual_fields={"bucket": "mybucket", "region": "eu-west-1", "prefix": "backups/"},
            credentials={"access_key_id": "AK", "secret_access_key": "SK"},
        )

    assert len(entries) == 1
    assert entries[0].name == "dump.sql.gz"
    assert entries[0].is_dir is False
