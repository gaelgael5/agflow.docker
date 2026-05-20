"""Tests pour /api/admin/pitr/config endpoints (GET + PUT) + basebackups (5 endpoints) + WAL + restore-window + clones."""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import jwt
from fastapi.testclient import TestClient


def _admin_token() -> str:
    return jwt.encode(
        {"sub": "admin@example.com", "role": "admin"},
        os.environ["JWT_SECRET"],
        algorithm="HS256",
    )


def _viewer_token() -> str:
    return jwt.encode(
        {"sub": "viewer@example.com", "role": "viewer"},
        os.environ["JWT_SECRET"],
        algorithm="HS256",
    )


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


_SEEDED_CONFIG = {
    "enabled": True,
    "basebackup_cron": "0 3 * * *",
    "retention_count": 7,
    "remote_connection_ids": [],
    "updated_at": datetime(2026, 5, 19, tzinfo=UTC).isoformat(),
}


# ── Auth guards ──────────────────────────────────────────────────────────


def test_get_config_401_without_token(client: TestClient) -> None:
    r = client.get("/api/admin/pitr/config")
    assert r.status_code == 401


def test_get_config_403_viewer(client: TestClient) -> None:
    r = client.get("/api/admin/pitr/config", headers=_auth(_viewer_token()))
    assert r.status_code == 403


def test_put_config_403_viewer(client: TestClient) -> None:
    r = client.put(
        "/api/admin/pitr/config",
        headers=_auth(_viewer_token()),
        json={"basebackup_cron": "0 4 * * *"},
    )
    assert r.status_code == 403


def test_put_config_401_without_token(client: TestClient) -> None:
    r = client.put(
        "/api/admin/pitr/config",
        json={"basebackup_cron": "0 4 * * *"},
    )
    assert r.status_code == 401


# ── GET /config ──────────────────────────────────────────────────────────


def test_get_config_returns_seeded(client: TestClient) -> None:
    from agflow.schemas.pitr import PitrConfigOut

    fake = PitrConfigOut(
        enabled=True,
        basebackup_cron="0 3 * * *",
        basebackup_type="diff",
        full_rebase_cron="0 2 * * 0",
        retention_count=7,
        remote_connection_ids=[],
        updated_at=datetime(2026, 5, 19, tzinfo=UTC),
    )
    with patch(
        "agflow.api.admin.pitr.pitr_config_service.get_config",
        AsyncMock(return_value=fake),
    ):
        r = client.get("/api/admin/pitr/config", headers=_auth(_admin_token()))
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True
    assert body["basebackup_cron"] == "0 3 * * *"
    assert body["retention_count"] == 7
    assert body["remote_connection_ids"] == []


# ── PUT /config ──────────────────────────────────────────────────────────


def test_put_config_updates_cron(client: TestClient) -> None:
    from agflow.schemas.pitr import PitrConfigOut

    updated = PitrConfigOut(
        enabled=True,
        basebackup_cron="0 4 * * *",
        basebackup_type="diff",
        full_rebase_cron="0 2 * * 0",
        retention_count=7,
        remote_connection_ids=[],
        updated_at=datetime(2026, 5, 19, tzinfo=UTC),
    )
    with (
        patch(
            "agflow.api.admin.pitr.pitr_config_service.update_config",
            AsyncMock(return_value=updated),
        ),
        patch(
            "agflow.api.admin.pitr.pitr_scheduler.reload_basebackup_schedule",
            AsyncMock(),
        ),
    ):
        r = client.put(
            "/api/admin/pitr/config",
            headers=_auth(_admin_token()),
            json={"basebackup_cron": "0 4 * * *"},
        )
    assert r.status_code == 200, r.text
    assert r.json()["basebackup_cron"] == "0 4 * * *"


def test_put_config_invalid_cron_422(client: TestClient) -> None:
    from agflow.services.pitr_config_service import InvalidCronError

    with patch(
        "agflow.api.admin.pitr.pitr_config_service.update_config",
        AsyncMock(side_effect=InvalidCronError("invalid cron expression 'not a cron'")),
    ):
        r = client.put(
            "/api/admin/pitr/config",
            headers=_auth(_admin_token()),
            json={"basebackup_cron": "not a cron"},
        )
    assert r.status_code == 422


def test_put_config_triggers_reload_when_cron_changes(client: TestClient) -> None:
    """Vérifie que reload_basebackup_schedule est appelé si basebackup_cron est fourni."""
    from agflow.schemas.pitr import PitrConfigOut

    updated = PitrConfigOut(
        enabled=True,
        basebackup_cron="0 2 * * *",
        basebackup_type="diff",
        full_rebase_cron="0 2 * * 0",
        retention_count=7,
        remote_connection_ids=[],
        updated_at=datetime(2026, 5, 19, tzinfo=UTC),
    )
    mock_reload = AsyncMock()
    with (
        patch(
            "agflow.api.admin.pitr.pitr_config_service.update_config",
            AsyncMock(return_value=updated),
        ),
        patch(
            "agflow.api.admin.pitr.pitr_scheduler.reload_basebackup_schedule",
            mock_reload,
        ),
    ):
        r = client.put(
            "/api/admin/pitr/config",
            headers=_auth(_admin_token()),
            json={"basebackup_cron": "0 2 * * *"},
        )
    assert r.status_code == 200
    mock_reload.assert_awaited_once()


def test_put_config_no_reload_when_only_retention_changes(client: TestClient) -> None:
    """reload_basebackup_schedule ne doit PAS être appelé si seul retention_count change."""
    from agflow.schemas.pitr import PitrConfigOut

    updated = PitrConfigOut(
        enabled=True,
        basebackup_cron="0 3 * * *",
        basebackup_type="diff",
        full_rebase_cron="0 2 * * 0",
        retention_count=14,
        remote_connection_ids=[],
        updated_at=datetime(2026, 5, 19, tzinfo=UTC),
    )
    mock_reload = AsyncMock()
    with (
        patch(
            "agflow.api.admin.pitr.pitr_config_service.update_config",
            AsyncMock(return_value=updated),
        ),
        patch(
            "agflow.api.admin.pitr.pitr_scheduler.reload_basebackup_schedule",
            mock_reload,
        ),
    ):
        r = client.put(
            "/api/admin/pitr/config",
            headers=_auth(_admin_token()),
            json={"retention_count": 14},
        )
    assert r.status_code == 200
    mock_reload.assert_not_awaited()


# ── Basebackups ───────────────────────────────────────────────────────────


def test_list_basebackups_returns_empty(client: TestClient) -> None:
    with patch(
        "agflow.api.admin.pitr.pitr_basebackup_service.list_basebackups",
        new=AsyncMock(return_value=[]),
    ):
        r = client.get("/api/admin/pitr/basebackups", headers=_auth(_admin_token()))
    assert r.status_code == 200
    assert r.json() == []


def test_get_basebackup_404(client: TestClient) -> None:
    from agflow.services.pitr_basebackup_service import BasebackupNotFoundError

    with patch(
        "agflow.api.admin.pitr.pitr_basebackup_service.get_basebackup",
        new=AsyncMock(side_effect=BasebackupNotFoundError("not-found")),
    ):
        r = client.get(
            f"/api/admin/pitr/basebackups/{uuid4()}",
            headers=_auth(_admin_token()),
        )
    assert r.status_code == 404


def test_trigger_basebackup_returns_id(client: TestClient) -> None:
    fake_id = uuid4()
    with patch(
        "agflow.api.admin.pitr.pitr_basebackup_service.trigger_basebackup_now",
        new=AsyncMock(return_value=fake_id),
    ):
        r = client.post("/api/admin/pitr/basebackups", headers=_auth(_admin_token()))
    assert r.status_code == 202
    assert r.json() == {"id": str(fake_id)}


def test_trigger_basebackup_409_when_already_running(client: TestClient) -> None:
    from agflow.services.pitr_basebackup_service import BasebackupRunningError

    with patch(
        "agflow.api.admin.pitr.pitr_basebackup_service.trigger_basebackup_now",
        new=AsyncMock(side_effect=BasebackupRunningError("already-running")),
    ):
        r = client.post("/api/admin/pitr/basebackups", headers=_auth(_admin_token()))
    assert r.status_code == 409


def test_delete_basebackup_204(client: TestClient) -> None:
    with patch(
        "agflow.api.admin.pitr.pitr_basebackup_service.delete_basebackup",
        new=AsyncMock(),
    ):
        r = client.delete(
            f"/api/admin/pitr/basebackups/{uuid4()}",
            headers=_auth(_admin_token()),
        )
    assert r.status_code == 204


def test_delete_basebackup_404(client: TestClient) -> None:
    from agflow.services.pitr_basebackup_service import BasebackupNotFoundError

    with patch(
        "agflow.api.admin.pitr.pitr_basebackup_service.delete_basebackup",
        new=AsyncMock(side_effect=BasebackupNotFoundError("not-found")),
    ):
        r = client.delete(
            f"/api/admin/pitr/basebackups/{uuid4()}",
            headers=_auth(_admin_token()),
        )
    assert r.status_code == 404


def test_delete_basebackup_409_if_last(client: TestClient) -> None:
    from agflow.services.pitr_basebackup_service import BasebackupIsLastError

    with patch(
        "agflow.api.admin.pitr.pitr_basebackup_service.delete_basebackup",
        new=AsyncMock(side_effect=BasebackupIsLastError("last-one")),
    ):
        r = client.delete(
            f"/api/admin/pitr/basebackups/{uuid4()}",
            headers=_auth(_admin_token()),
        )
    assert r.status_code == 409


def test_push_basebackup_202(client: TestClient) -> None:
    with patch(
        "agflow.api.admin.pitr.pitr_basebackup_pushes_service.push_basebackup",
        new=AsyncMock(),
    ):
        r = client.post(
            f"/api/admin/pitr/basebackups/{uuid4()}/push/{uuid4()}",
            headers=_auth(_admin_token()),
        )
    assert r.status_code == 202
    assert r.json() == {"status": "queued"}


def test_push_basebackup_404_push_not_found(client: TestClient) -> None:
    from agflow.services.pitr_basebackup_pushes_service import PushNotFoundError

    with patch(
        "agflow.api.admin.pitr.pitr_basebackup_pushes_service.push_basebackup",
        new=AsyncMock(side_effect=PushNotFoundError("not-found")),
    ):
        r = client.post(
            f"/api/admin/pitr/basebackups/{uuid4()}/push/{uuid4()}",
            headers=_auth(_admin_token()),
        )
    assert r.status_code == 404


def test_push_basebackup_404_basebackup_not_found(client: TestClient) -> None:
    from agflow.services.pitr_basebackup_service import BasebackupNotFoundError

    with patch(
        "agflow.api.admin.pitr.pitr_basebackup_pushes_service.push_basebackup",
        new=AsyncMock(side_effect=BasebackupNotFoundError("not-found")),
    ):
        r = client.post(
            f"/api/admin/pitr/basebackups/{uuid4()}/push/{uuid4()}",
            headers=_auth(_admin_token()),
        )
    assert r.status_code == 404


# ── WAL status + restore window ───────────────────────────────────────────


def test_wal_status_returns_payload(client: TestClient) -> None:
    from agflow.schemas.pitr import WalStatus

    fake_status = WalStatus(
        archiving_enabled=True,
        last_archived_at=None,
        archive_lag_seconds=None,
        wal_disk_used_bytes=1_000_000,
        wal_disk_free_bytes=50_000_000_000,
    )
    with patch(
        "agflow.api.admin.pitr.pitr_wal_archive_service.get_wal_status",
        new=AsyncMock(return_value=fake_status),
    ):
        r = client.get("/api/admin/pitr/wal-status", headers=_auth(_admin_token()))
    assert r.status_code == 200
    body = r.json()
    assert body["archiving_enabled"] is True
    assert body["wal_disk_used_bytes"] == 1_000_000


def test_wal_status_viewer_403(client: TestClient) -> None:
    r = client.get("/api/admin/pitr/wal-status", headers=_auth(_viewer_token()))
    assert r.status_code == 403


def test_restore_window_returns_bounds(client: TestClient) -> None:
    from datetime import timedelta

    from agflow.schemas.pitr import RestoreWindow

    earliest = datetime.now(UTC) - timedelta(days=7)
    latest = datetime.now(UTC) - timedelta(hours=1)
    fake_win = RestoreWindow(earliest=earliest, latest=latest)
    with patch(
        "agflow.api.admin.pitr.pitr_restore_service.get_restore_window",
        new=AsyncMock(return_value=fake_win),
    ):
        r = client.get("/api/admin/pitr/restore-window", headers=_auth(_admin_token()))
    assert r.status_code == 200
    body = r.json()
    assert "earliest" in body
    assert "latest" in body


def test_restore_window_404_when_empty(client: TestClient) -> None:
    from agflow.services.pitr_restore_service import RestoreWindowEmptyError

    with patch(
        "agflow.api.admin.pitr.pitr_restore_service.get_restore_window",
        new=AsyncMock(side_effect=RestoreWindowEmptyError("nope")),
    ):
        r = client.get("/api/admin/pitr/restore-window", headers=_auth(_admin_token()))
    assert r.status_code == 404


# ── Clones ────────────────────────────────────────────────────────────────


def _now_utc() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _make_clone_status(*, status: str = "ready", clone_id: UUID | None = None):  # type: ignore[return]
    from agflow.schemas.pitr import CloneStatus

    cid = clone_id or uuid4()
    now = _now_utc()
    return CloneStatus(
        id=cid,
        basebackup_id=uuid4(),
        basebackup_label="20260520-030000F",
        target_time=now - timedelta(hours=1),
        status=status,
        error=None,
        pgweb_url="http://192.168.10.158:32768" if status == "ready" else None,
        started_at=now - timedelta(minutes=5),
        ready_at=now - timedelta(minutes=4) if status == "ready" else None,
        expires_at=now + timedelta(hours=24),
        expires_in_seconds=86400,
    )


def test_start_clone_returns_id(client: TestClient) -> None:
    fake_id = uuid4()
    with patch(
        "agflow.api.admin.pitr.pitr_restore_service.start_clone",
        new=AsyncMock(return_value=fake_id),
    ):
        r = client.post(
            "/api/admin/pitr/clones",
            headers=_auth(_admin_token()),
            json={"target_time": _now_utc().isoformat()},
        )
    assert r.status_code == 202
    assert r.json() == {"id": str(fake_id)}


def test_start_clone_422_out_of_window(client: TestClient) -> None:
    from agflow.services.pitr_restore_service import InvalidTargetTimeError

    with patch(
        "agflow.api.admin.pitr.pitr_restore_service.start_clone",
        new=AsyncMock(side_effect=InvalidTargetTimeError("out of window")),
    ):
        r = client.post(
            "/api/admin/pitr/clones",
            headers=_auth(_admin_token()),
            json={"target_time": _now_utc().isoformat()},
        )
    assert r.status_code == 422


def test_start_clone_404_window_empty(client: TestClient) -> None:
    from agflow.services.pitr_restore_service import RestoreWindowEmptyError

    with patch(
        "agflow.api.admin.pitr.pitr_restore_service.start_clone",
        new=AsyncMock(side_effect=RestoreWindowEmptyError("no basebackup")),
    ):
        r = client.post(
            "/api/admin/pitr/clones",
            headers=_auth(_admin_token()),
            json={"target_time": _now_utc().isoformat()},
        )
    assert r.status_code == 404


def test_start_clone_409_already_active(client: TestClient) -> None:
    from agflow.services.pitr_restore_service import CloneAlreadyActiveError

    with patch(
        "agflow.api.admin.pitr.pitr_restore_service.start_clone",
        new=AsyncMock(side_effect=CloneAlreadyActiveError("xxx")),
    ):
        r = client.post(
            "/api/admin/pitr/clones",
            headers=_auth(_admin_token()),
            json={"target_time": _now_utc().isoformat()},
        )
    assert r.status_code == 409


def test_get_active_clone_returns_null_when_no_active(client: TestClient) -> None:
    with patch(
        "agflow.api.admin.pitr.pitr_clone_service.get_active_clone",
        new=AsyncMock(return_value=None),
    ):
        r = client.get("/api/admin/pitr/clones/active", headers=_auth(_admin_token()))
    assert r.status_code == 200
    assert r.json() is None


def test_get_active_clone_returns_clone(client: TestClient) -> None:
    fake = _make_clone_status(status="ready")
    with patch(
        "agflow.api.admin.pitr.pitr_clone_service.get_active_clone",
        new=AsyncMock(return_value=fake),
    ):
        r = client.get("/api/admin/pitr/clones/active", headers=_auth(_admin_token()))
    assert r.status_code == 200
    assert r.json()["status"] == "ready"


def test_extend_active_clone_returns_refreshed(client: TestClient) -> None:
    fake = _make_clone_status(status="ready")
    with patch(
        "agflow.api.admin.pitr.pitr_clone_service.extend_active_clone",
        new=AsyncMock(return_value=fake),
    ):
        r = client.post(
            "/api/admin/pitr/clones/active/extend", headers=_auth(_admin_token())
        )
    assert r.status_code == 200
    assert r.json()["id"] == str(fake.id)


def test_extend_active_clone_404_when_no_active(client: TestClient) -> None:
    from agflow.services.pitr_clone_service import NoActiveCloneError

    with patch(
        "agflow.api.admin.pitr.pitr_clone_service.extend_active_clone",
        new=AsyncMock(side_effect=NoActiveCloneError()),
    ):
        r = client.post(
            "/api/admin/pitr/clones/active/extend", headers=_auth(_admin_token())
        )
    assert r.status_code == 404


def test_terminate_active_clone_204(client: TestClient) -> None:
    with patch(
        "agflow.api.admin.pitr.pitr_clone_service.terminate_active_clone",
        new=AsyncMock(),
    ):
        r = client.delete("/api/admin/pitr/clones/active", headers=_auth(_admin_token()))
    assert r.status_code == 204


def test_terminate_active_clone_404_when_no_active(client: TestClient) -> None:
    from agflow.services.pitr_clone_service import NoActiveCloneError

    with patch(
        "agflow.api.admin.pitr.pitr_clone_service.terminate_active_clone",
        new=AsyncMock(side_effect=NoActiveCloneError()),
    ):
        r = client.delete("/api/admin/pitr/clones/active", headers=_auth(_admin_token()))
    assert r.status_code == 404
