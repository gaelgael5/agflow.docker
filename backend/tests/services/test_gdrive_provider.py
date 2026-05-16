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
