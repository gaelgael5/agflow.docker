from __future__ import annotations

import pytest

from agflow.services.remote_backup_providers.factory import get_provider
from agflow.services.remote_backup_providers.gdrive_provider import GoogleDriveProvider
from agflow.services.remote_backup_providers.protocol import RemoteBackupProviderError


def test_factory_returns_gdrive_provider_for_kind_gdrive() -> None:
    config = {"folder_id": "abc"}
    credentials = {
        "client_id": "x.apps.googleusercontent.com",
        "client_secret": "GOCSPX-x",
        "refresh_token": "x",
        "token_uri": "https://oauth2.googleapis.com/token",
        "scope": "https://www.googleapis.com/auth/drive.file",
    }
    p = get_provider("gdrive", config, credentials)
    assert isinstance(p, GoogleDriveProvider)


def test_factory_unknown_kind_still_raises() -> None:
    with pytest.raises(RemoteBackupProviderError, match="Unknown kind"):
        get_provider("dropbox", {}, {})
