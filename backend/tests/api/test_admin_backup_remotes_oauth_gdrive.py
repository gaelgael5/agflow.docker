"""Tests des 5 endpoints OAuth gdrive (mocks du service)."""
from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import jwt
from fastapi.testclient import TestClient


def _admin_token() -> str:
    return jwt.encode(
        {"sub": "admin@example.com", "role": "admin"},
        os.environ["JWT_SECRET"], algorithm="HS256",
    )


def _viewer_token() -> str:
    return jwt.encode(
        {"sub": "viewer@example.com", "role": "viewer"},
        os.environ["JWT_SECRET"], algorithm="HS256",
    )


def test_redirect_uri_requires_admin(client: TestClient) -> None:
    r = client.get("/api/admin/backup-remotes/oauth/gdrive/redirect-uri")
    assert r.status_code == 401


def test_redirect_uri_returns_callback_url(client: TestClient) -> None:
    r = client.get(
        "/api/admin/backup-remotes/oauth/gdrive/redirect-uri",
        headers={"Authorization": f"Bearer {_admin_token()}"},
    )
    assert r.status_code == 200
    assert "/api/admin/backup-remotes/oauth/gdrive/callback" in r.json()["redirect_uri"]


def test_start_returns_state_and_authorize_url(client: TestClient) -> None:
    _fake_admin = SimpleNamespace(id=uuid4())
    with (
        patch(
            "agflow.api.admin.remote_backup_connections.gdrive_oauth_session.start_session",
            AsyncMock(return_value=("abc123def", "https://accounts.google.com/o/oauth2/auth?state=abc")),
        ),
        patch(
            "agflow.api.admin.remote_backup_connections.users_service.get_by_email",
            AsyncMock(return_value=_fake_admin),
        ),
    ):
        r = client.post(
            "/api/admin/backup-remotes/oauth/gdrive/start",
            headers={"Authorization": f"Bearer {_admin_token()}"},
            json={
                "name": "My Backups",
                "folder_name": "agflow-backups",
                "client_id": "x.apps.googleusercontent.com",
                "client_secret": "GOCSPX-x",
            },
        )
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "abc123def"
    assert "accounts.google.com" in body["authorize_url"]


def test_start_rejects_viewer(client: TestClient) -> None:
    r = client.post(
        "/api/admin/backup-remotes/oauth/gdrive/start",
        headers={"Authorization": f"Bearer {_viewer_token()}"},
        json={"name": "x", "folder_name": "x", "client_id": "x", "client_secret": "x"},
    )
    assert r.status_code == 403


def test_session_returns_status(client: TestClient) -> None:
    with patch(
        "agflow.api.admin.remote_backup_connections.gdrive_oauth_session.get_session",
        AsyncMock(return_value={"status": "completed", "connection_id": uuid4(), "user_email": "u@x", "folder_id": "f"}),
    ):
        r = client.get(
            "/api/admin/backup-remotes/oauth/gdrive/session/somestate",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 200
    assert r.json()["status"] == "completed"


def test_session_returns_404_when_unknown(client: TestClient) -> None:
    with patch(
        "agflow.api.admin.remote_backup_connections.gdrive_oauth_session.get_session",
        AsyncMock(return_value=None),
    ):
        r = client.get(
            "/api/admin/backup-remotes/oauth/gdrive/session/unknown",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 404


def test_callback_redirects_with_postmessage_html(client: TestClient) -> None:
    with patch(
        "agflow.api.admin.remote_backup_connections.gdrive_oauth_session.consume_session",
        AsyncMock(return_value={"connection_id": uuid4(), "user_email": "u@x", "folder_id": "f"}),
    ):
        r = client.get(
            "/api/admin/backup-remotes/oauth/gdrive/callback?state=abc&code=xyz",
            follow_redirects=False,
        )
    # Public endpoint, retourne HTML (pas de 401)
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "window.close" in r.text or "postMessage" in r.text


def test_reauthorize_returns_state_and_url(client: TestClient) -> None:
    _fake_admin = SimpleNamespace(id=uuid4())
    with (
        patch(
            "agflow.api.admin.remote_backup_connections.gdrive_oauth_session.reauthorize",
            AsyncMock(return_value=("newstate", "https://accounts.google.com/o/oauth2/auth?state=newstate")),
        ),
        patch(
            "agflow.api.admin.remote_backup_connections.users_service.get_by_email",
            AsyncMock(return_value=_fake_admin),
        ),
    ):
        r = client.post(
            f"/api/admin/backup-remotes/{uuid4()}/reauthorize",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 200
    assert r.json()["state"] == "newstate"


def test_create_kind_gdrive_returns_400(client: TestClient) -> None:
    r = client.post(
        "/api/admin/backup-remotes",
        headers={"Authorization": f"Bearer {_admin_token()}"},
        json={"kind": "gdrive", "name": "x", "config": {}, "credentials": {}},
    )
    assert r.status_code == 400
    assert "oauth/gdrive/start" in r.text
