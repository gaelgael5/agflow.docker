from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from agflow.auth.dependencies import require_admin
from agflow.main import create_app


def _make_fake_pool():
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
    app.dependency_overrides[require_admin] = lambda: "admin@example.com"
    return TestClient(app)


# ---------- GET /api/admin/backup-remotes/{id}/files ----------


def test_list_remote_files_returns_files(client):
    remote_id = uuid4()
    fake_pool = _make_fake_pool()

    remote_file = MagicMock(
        filename="a.sql.gz",
        size_bytes=1024,
        last_modified=datetime(2026, 5, 1),
    )
    provider = MagicMock()
    provider.list_remote = AsyncMock(return_value=[remote_file])

    with (
        patch(
            "agflow.api.admin.remote_backup_connections.get_pool",
            AsyncMock(return_value=fake_pool),
        ),
        patch(
            "agflow.api.admin.remote_backup_connections.rbc_service.get_connection",
            AsyncMock(
                return_value=MagicMock(
                    id=remote_id,
                    kind="sftp",
                    config={"remote_path_full": "/backups"},
                )
            ),
        ),
        patch(
            "agflow.api.admin.remote_backup_connections.rbc_service.fetch_credentials",
            AsyncMock(return_value={"username": "u"}),
        ),
        patch(
            "agflow.api.admin.remote_backup_connections.rbc_service.resolve_remote_path",
            MagicMock(return_value="/backups"),
        ),
        patch(
            "agflow.api.admin.remote_backup_connections.get_provider",
            return_value=provider,
        ),
    ):
        resp = client.get(f"/api/admin/backup-remotes/{remote_id}/files")

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["filename"] == "a.sql.gz"
    provider.list_remote.assert_called_once_with("/backups")


def test_list_remote_files_404_if_connection_missing(client):
    fake_pool = _make_fake_pool()
    with (
        patch(
            "agflow.api.admin.remote_backup_connections.get_pool",
            AsyncMock(return_value=fake_pool),
        ),
        patch(
            "agflow.api.admin.remote_backup_connections.rbc_service.get_connection",
            AsyncMock(return_value=None),
        ),
    ):
        resp = client.get(f"/api/admin/backup-remotes/{uuid4()}/files")
    assert resp.status_code == 404


def test_list_remote_files_422_on_provider_error(client):
    from agflow.services.remote_backup_providers import RemoteBackupProviderError

    fake_pool = _make_fake_pool()
    provider = MagicMock()
    provider.list_remote = AsyncMock(side_effect=RemoteBackupProviderError("nope"))

    with (
        patch(
            "agflow.api.admin.remote_backup_connections.get_pool",
            AsyncMock(return_value=fake_pool),
        ),
        patch(
            "agflow.api.admin.remote_backup_connections.rbc_service.get_connection",
            AsyncMock(
                return_value=MagicMock(id=uuid4(), kind="sftp", config={})
            ),
        ),
        patch(
            "agflow.api.admin.remote_backup_connections.rbc_service.fetch_credentials",
            AsyncMock(return_value={"username": "u"}),
        ),
        patch(
            "agflow.api.admin.remote_backup_connections.rbc_service.resolve_remote_path",
            MagicMock(return_value="/backups"),
        ),
        patch(
            "agflow.api.admin.remote_backup_connections.get_provider",
            return_value=provider,
        ),
    ):
        resp = client.get(f"/api/admin/backup-remotes/{uuid4()}/files")

    assert resp.status_code == 422


# ---------- POST /api/admin/local-backups/pull-from-remote/{id} ----------


def test_pull_from_remote_calls_service(client):
    from datetime import datetime

    from agflow.schemas.local_backups import LocalBackupSummary

    remote_id = uuid4()
    backup_uuid = uuid4()
    fake_summary = LocalBackupSummary(
        id=backup_uuid,
        filename="x.sql.gz",
        size_bytes=12,
        status="completed",
        created_at=datetime(2026, 5, 14),
        source_remote_connection_id=remote_id,
    )

    with (
        patch(
            "agflow.api.admin.local_backups.users_service.get_by_email",
            new=AsyncMock(return_value=MagicMock(id=uuid4())),
        ),
        patch(
            "agflow.api.admin.local_backups.local_backups_service.pull_remote_to_local",
            new=AsyncMock(return_value=fake_summary),
        ) as mock_pull,
    ):
        resp = client.post(
            f"/api/admin/local-backups/pull-from-remote/{remote_id}",
            json={"filename": "x.sql.gz"},
        )

    assert resp.status_code == 201
    mock_pull.assert_awaited_once()
    _, kwargs = mock_pull.call_args
    assert kwargs["filename"] == "x.sql.gz"


def test_pull_from_remote_rejects_path_separator(client):
    resp = client.post(
        f"/api/admin/local-backups/pull-from-remote/{uuid4()}",
        json={"filename": "evil/escape.sql.gz"},
    )
    assert resp.status_code == 422


# ---------- POST /api/admin/local-backups/{id}/restore ----------


def test_restore_local_backup_requires_filename_match(client):
    backup_id = uuid4()
    with patch(
        "agflow.api.admin.local_backups.local_backups_service.get_backup",
        new=AsyncMock(return_value=MagicMock(filename="actual.sql.gz")),
    ):
        resp = client.post(
            f"/api/admin/local-backups/{backup_id}/restore",
            json={"filename": "wrong.sql.gz"},
        )

    assert resp.status_code == 422
    assert "match" in resp.json()["detail"].lower()


def test_restore_local_backup_success(client):
    from agflow.schemas.remote_backup_files import RestoreResult

    backup_id = uuid4()
    fake_result = RestoreResult(
        backup_id=backup_id, exit_code=0, output_tail="DONE"
    )

    with (
        patch(
            "agflow.api.admin.local_backups.local_backups_service.get_backup",
            new=AsyncMock(return_value=MagicMock(filename="x.sql.gz")),
        ),
        patch(
            "agflow.api.admin.local_backups.restore_service.restore_local_backup",
            new=AsyncMock(return_value=fake_result),
        ),
    ):
        resp = client.post(
            f"/api/admin/local-backups/{backup_id}/restore",
            json={"filename": "x.sql.gz"},
        )

    assert resp.status_code == 200
    assert resp.json()["exit_code"] == 0


def test_restore_local_backup_404_if_missing(client):
    with patch(
        "agflow.api.admin.local_backups.local_backups_service.get_backup",
        new=AsyncMock(return_value=None),
    ):
        resp = client.post(
            f"/api/admin/local-backups/{uuid4()}/restore",
            json={"filename": "x.sql.gz"},
        )
    assert resp.status_code == 404
