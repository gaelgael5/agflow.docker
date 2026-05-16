"""Tests purs des helpers gdrive_client (mocks du SDK Google)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from agflow.services.remote_backup_providers import gdrive_client


def test_build_credentials_returns_credentials_from_dict() -> None:
    creds_dict = {
        "client_id": "abc.apps.googleusercontent.com",
        "client_secret": "GOCSPX-secret",
        "refresh_token": "1//0g-refresh",
        "token_uri": "https://oauth2.googleapis.com/token",
        "scope": "https://www.googleapis.com/auth/drive.file",
    }
    creds = gdrive_client.build_credentials(creds_dict)
    assert creds.client_id == creds_dict["client_id"]
    assert creds.refresh_token == creds_dict["refresh_token"]


def test_build_flow_returns_flow_with_correct_scopes() -> None:
    flow = gdrive_client.build_flow(
        client_id="abc.apps.googleusercontent.com",
        client_secret="GOCSPX-secret",
        redirect_uri="https://example.com/cb",
    )
    assert "https://www.googleapis.com/auth/drive.file" in flow.oauth2session.scope


def test_build_drive_service_calls_googleapiclient_build() -> None:
    fake_creds = MagicMock()
    with patch(
        "agflow.services.remote_backup_providers.gdrive_client.build"
    ) as mock_build:
        gdrive_client.build_drive_service(fake_creds)
        mock_build.assert_called_once_with(
            "drive", "v3", credentials=fake_creds, cache_discovery=False,
        )


@pytest.mark.asyncio
async def test_fetch_user_email_returns_email_from_userinfo() -> None:
    fake_creds = MagicMock()
    with patch(
        "agflow.services.remote_backup_providers.gdrive_client.build"
    ) as mock_build:
        mock_service = MagicMock()
        mock_service.userinfo().get().execute.return_value = {
            "email": "user@example.com",
        }
        mock_build.return_value = mock_service
        email = await gdrive_client.fetch_user_email(fake_creds)
    assert email == "user@example.com"


@pytest.mark.asyncio
async def test_refresh_calls_credentials_refresh() -> None:
    fake_creds = MagicMock()
    with patch(
        "agflow.services.remote_backup_providers.gdrive_client.Request"
    ) as mock_request:
        await gdrive_client.refresh(fake_creds)
        fake_creds.refresh.assert_called_once_with(mock_request.return_value)
