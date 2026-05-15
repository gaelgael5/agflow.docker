from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from agflow.auth.dependencies import require_admin
from agflow.main import create_app


def _make_fake_pool():
    """Retourne un pool mock dont .acquire() est un async context manager."""
    fake_conn = AsyncMock()
    fake_pool = MagicMock()

    @asynccontextmanager
    async def _acquire():
        yield fake_conn

    fake_pool.acquire = _acquire
    return fake_pool


@pytest.fixture
def client():
    app = create_app()
    # Bypass JWT auth : require_admin retourne l'email de l'admin fictif
    app.dependency_overrides[require_admin] = lambda: "admin@example.com"
    return TestClient(app)


def test_test_connection_always_returns_200_on_provider_error(client):
    """POST /api/admin/backup-remotes/test retourne 200 même si provider échoue."""
    from agflow.services.remote_backup_providers import RemoteBackupProviderError

    with patch(
        "agflow.api.admin.remote_backup_connections.get_provider",
    ) as mock_factory:
        mock_provider = AsyncMock()
        mock_provider.test_connection = AsyncMock(
            side_effect=RemoteBackupProviderError("Connection refused")
        )
        mock_factory.return_value = mock_provider

        resp = client.post(
            "/api/admin/backup-remotes/test",
            json={
                "kind": "sftp",
                "config": {"host": "sftp.example.com", "port": 22},
                "credentials": {"username": "u", "password": "p"},
                "path": "/backups",
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert "Connection refused" in data.get("message", "")


def test_create_connection_returns_409_on_duplicate_name(client):
    """POST /api/admin/backup-remotes retourne 409 si le nom existe déjà."""
    import asyncpg

    fake_pool = _make_fake_pool()

    with (
        patch(
            "agflow.api.admin.remote_backup_connections.get_pool",
            AsyncMock(return_value=fake_pool),
        ),
        patch(
            "agflow.api.admin.remote_backup_connections.rbc_service.create_connection",
            AsyncMock(side_effect=asyncpg.UniqueViolationError()),
        ),
    ):
        resp = client.post(
            "/api/admin/backup-remotes",
            json={"name": "existing", "kind": "sftp", "config": {}},
        )

    assert resp.status_code == 409
