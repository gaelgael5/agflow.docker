"""Tests des 4 méthodes Protocol du GoogleDriveProvider (mocks SDK)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agflow.services.remote_backup_providers.gdrive_provider import GoogleDriveProvider
from agflow.services.remote_backup_providers.protocol import RemoteBackupProviderError

_CONFIG = {
    "client_id": "abc.apps.googleusercontent.com",
    "redirect_uri": "https://example.com/cb",
    "folder_name": "agflow-backups",
    "folder_id": "1a2B3c4D5e",
    "user_email": "ops@example.com",
}
_CREDS = {
    "client_id": _CONFIG["client_id"],
    "client_secret": "GOCSPX-secret",
    "refresh_token": "1//0g-refresh",
    "token_uri": "https://oauth2.googleapis.com/token",
    "scope": "https://www.googleapis.com/auth/drive.file",
}


@pytest.mark.asyncio
async def test_test_connection_lists_folder_ok() -> None:
    provider = GoogleDriveProvider(config=_CONFIG, credentials=_CREDS)
    fake_service = MagicMock()
    fake_service.files().list().execute.return_value = {"files": []}
    with patch(
        "agflow.services.remote_backup_providers.gdrive_provider.gdrive_client.build_drive_service",
        return_value=fake_service,
    ):
        await provider.test_connection(path="")
    # Pas d'erreur = succès
    fake_service.files().list.assert_called()


@pytest.mark.asyncio
async def test_test_connection_raises_on_http_error() -> None:
    from googleapiclient.errors import HttpError

    provider = GoogleDriveProvider(config=_CONFIG, credentials=_CREDS)
    fake_service = MagicMock()
    fake_resp = MagicMock(status=404, reason="Not Found")
    fake_service.files().list().execute.side_effect = HttpError(
        resp=fake_resp, content=b'{"error": "Folder not found"}',
    )
    with (
        patch(
            "agflow.services.remote_backup_providers.gdrive_provider.gdrive_client.build_drive_service",
            return_value=fake_service,
        ),
        pytest.raises(RemoteBackupProviderError, match="404"),
    ):
        await provider.test_connection(path="")


@pytest.mark.asyncio
async def test_upload_stream_writes_to_drive_and_returns_size() -> None:
    async def _source():
        yield b"chunk1-"
        yield b"chunk2"

    provider = GoogleDriveProvider(config=_CONFIG, credentials=_CREDS)
    fake_service = MagicMock()
    fake_service.files().create().execute.return_value = {"id": "fileXYZ"}
    with patch(
        "agflow.services.remote_backup_providers.gdrive_provider.gdrive_client.build_drive_service",
        return_value=fake_service,
    ):
        size = await provider.upload_stream(
            path="", filename="backup.sql.gz", source=_source(),
        )
    assert size == len(b"chunk1-chunk2")
    fake_service.files().create.assert_called()


@pytest.mark.asyncio
async def test_upload_stream_maps_http_error_to_provider_error() -> None:
    from googleapiclient.errors import HttpError

    async def _source():
        yield b"data"

    provider = GoogleDriveProvider(config=_CONFIG, credentials=_CREDS)
    fake_service = MagicMock()
    fake_resp = MagicMock(status=403, reason="Quota Exceeded")
    fake_service.files().create().execute.side_effect = HttpError(
        resp=fake_resp, content=b'{"error": "quota"}',
    )
    with patch(
        "agflow.services.remote_backup_providers.gdrive_provider.gdrive_client.build_drive_service",
        return_value=fake_service,
    ), pytest.raises(RemoteBackupProviderError, match="403"):
        await provider.upload_stream(path="", filename="b.sql", source=_source())


@pytest.mark.asyncio
async def test_list_remote_returns_remote_files() -> None:
    provider = GoogleDriveProvider(config=_CONFIG, credentials=_CREDS)
    fake_service = MagicMock()
    fake_service.files().list().execute.return_value = {
        "files": [
            {
                "id": "f1", "name": "backup-2026-05-15.sql.gz",
                "size": "12345", "modifiedTime": "2026-05-15T10:00:00.000Z",
            },
            {
                "id": "f2", "name": "backup-2026-05-16.sql.gz",
                "size": "23456", "modifiedTime": "2026-05-16T10:00:00.000Z",
            },
        ],
    }
    with patch(
        "agflow.services.remote_backup_providers.gdrive_provider.gdrive_client.build_drive_service",
        return_value=fake_service,
    ):
        files = await provider.list_remote(path="")
    assert len(files) == 2
    assert files[0].filename == "backup-2026-05-15.sql.gz"
    assert files[0].size_bytes == 12345
    assert files[0].last_modified is not None
