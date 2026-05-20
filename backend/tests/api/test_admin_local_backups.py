from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from agflow.auth.dependencies import require_admin
from agflow.main import create_app


@pytest.fixture
def client():
    app = create_app()
    app.dependency_overrides[require_admin] = lambda: "admin@example.com"
    return TestClient(app)


# ---------------------------------------------------------------------------
# GET /{backup_id}/pushes
# ---------------------------------------------------------------------------


def test_get_pushes_returns_list(client: TestClient):
    from agflow.schemas.local_backup_pushes import LocalBackupPushSummary

    fake_pushes = [
        LocalBackupPushSummary(
            id=uuid4(),
            local_backup_id=uuid4(),
            remote_connection_id=uuid4(),
            remote_connection_name="r1",
            status="ok",
            pushed_at=datetime.now(UTC),
            error=None,
            remote_path="full/x.dump",
            size_bytes=1024,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
    ]
    with patch(
        "agflow.api.admin.local_backups.local_backup_pushes_service.list_pushes",
        new=AsyncMock(return_value=fake_pushes),
    ):
        r = client.get(f"/api/admin/local-backups/{uuid4()}/pushes")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["status"] == "ok"


def test_get_pushes_returns_empty_list(client: TestClient):
    with patch(
        "agflow.api.admin.local_backups.local_backup_pushes_service.list_pushes",
        new=AsyncMock(return_value=[]),
    ):
        r = client.get(f"/api/admin/local-backups/{uuid4()}/pushes")
    assert r.status_code == 200
    assert r.json() == []


# ---------------------------------------------------------------------------
# POST /{backup_id}/push/{remote_id}
# ---------------------------------------------------------------------------


def test_post_push_202(client: TestClient):
    from agflow.schemas.local_backup_pushes import LocalBackupPushSummary

    fake_result = LocalBackupPushSummary(
        id=uuid4(),
        local_backup_id=uuid4(),
        remote_connection_id=uuid4(),
        remote_connection_name="r1",
        status="ok",
        pushed_at=datetime.now(UTC),
        error=None,
        remote_path="full/x.dump",
        size_bytes=1024,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    with patch(
        "agflow.api.admin.local_backups.local_backup_pushes_service.push_one",
        new=AsyncMock(return_value=fake_result),
    ):
        r = client.post(
            f"/api/admin/local-backups/{uuid4()}/push/{uuid4()}",
        )
    assert r.status_code == 202
    assert r.json() == {"status": "ok"}


def test_post_push_404_push_not_found(client: TestClient):
    from agflow.services import local_backup_pushes_service

    with patch(
        "agflow.api.admin.local_backups.local_backup_pushes_service.push_one",
        new=AsyncMock(
            side_effect=local_backup_pushes_service.PushNotFoundError("nope")
        ),
    ):
        r = client.post(
            f"/api/admin/local-backups/{uuid4()}/push/{uuid4()}",
        )
    assert r.status_code == 404
    assert "push not found" in r.json()["detail"]


def test_post_push_409_local_file_missing(client: TestClient):
    from agflow.services import local_backup_pushes_service

    with patch(
        "agflow.api.admin.local_backups.local_backup_pushes_service.push_one",
        new=AsyncMock(
            side_effect=local_backup_pushes_service.LocalFileMissingError("file gone")
        ),
    ):
        r = client.post(
            f"/api/admin/local-backups/{uuid4()}/push/{uuid4()}",
        )
    assert r.status_code == 409
    assert "local file missing" in r.json()["detail"]
