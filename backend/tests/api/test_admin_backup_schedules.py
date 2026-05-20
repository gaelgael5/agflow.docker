"""Tests intégration HTTP des 12 endpoints backup_schedules (mocks service)."""
from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import jwt
from fastapi.testclient import TestClient

from agflow.schemas.backup_schedules import FullScheduleSummary


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


def _full_summary(name: str = "s", enabled: bool = True) -> FullScheduleSummary:
    return FullScheduleSummary(
        id=uuid4(), name=name, cron_expr="0 * * * *",
        remote_connection_ids=[], keep_local=True, retention_count=10, enabled=enabled,
        last_run_at=None, last_run_status=None, last_run_error=None,
        created_at=datetime(2026, 5, 16, tzinfo=UTC),
        updated_at=datetime(2026, 5, 16, tzinfo=UTC),
    )


# ── Auth ────────────────────────────────────────────────────────────────


def test_list_full_requires_token(client: TestClient) -> None:
    r = client.get("/api/admin/backup-schedules/full")
    assert r.status_code == 401


def test_list_full_rejects_viewer(client: TestClient) -> None:
    r = client.get(
        "/api/admin/backup-schedules/full",
        headers={"Authorization": f"Bearer {_viewer_token()}"},
    )
    assert r.status_code == 403


# ── Full CRUD ──────────────────────────────────────────────────────────


def test_list_full_returns_summaries(client: TestClient) -> None:
    fake = [_full_summary("a"), _full_summary("b", enabled=False)]
    with patch(
        "agflow.api.admin.backup_schedules.svc.list_full_schedules",
        AsyncMock(return_value=fake),
    ):
        r = client.get(
            "/api/admin/backup-schedules/full",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 200
    assert len(r.json()) == 2


def test_create_full_returns_201(client: TestClient) -> None:
    with (
        patch(
            "agflow.api.admin.backup_schedules.users_service.get_by_email",
            AsyncMock(return_value=type("U", (), {"id": uuid4()})()),
        ),
        patch(
            "agflow.api.admin.backup_schedules.svc.create_full_schedule",
            AsyncMock(return_value=_full_summary("new")),
        ),
    ):
        r = client.post(
            "/api/admin/backup-schedules/full",
            headers={"Authorization": f"Bearer {_admin_token()}"},
            json={
                "name": "new",
                "cron_expr": "0 3 * * *",
                "remote_connection_ids": [],
                "keep_local": True,
            },
        )
    assert r.status_code == 201
    assert r.json()["name"] == "new"


def test_create_full_returns_422_on_invalid_cron(client: TestClient) -> None:
    from agflow.services.backup_schedules_service import InvalidCronExpressionError
    with (
        patch(
            "agflow.api.admin.backup_schedules.users_service.get_by_email",
            AsyncMock(return_value=type("U", (), {"id": uuid4()})()),
        ),
        patch(
            "agflow.api.admin.backup_schedules.svc.create_full_schedule",
            AsyncMock(side_effect=InvalidCronExpressionError("bad cron")),
        ),
    ):
        r = client.post(
            "/api/admin/backup-schedules/full",
            headers={"Authorization": f"Bearer {_admin_token()}"},
            json={
                "name": "x",
                "cron_expr": "bad",
                "remote_connection_ids": [],
                "keep_local": True,
            },
        )
    assert r.status_code == 422


def test_update_full_404(client: TestClient) -> None:
    from agflow.services.backup_schedules_service import ScheduleNotFoundError
    with patch(
        "agflow.api.admin.backup_schedules.svc.update_full_schedule",
        AsyncMock(side_effect=ScheduleNotFoundError("nope")),
    ):
        r = client.put(
            f"/api/admin/backup-schedules/full/{uuid4()}",
            headers={"Authorization": f"Bearer {_admin_token()}"},
            json={"name": "y", "remote_connection_ids": [], "keep_local": True},
        )
    assert r.status_code == 404


def test_delete_full_204(client: TestClient) -> None:
    with patch(
        "agflow.api.admin.backup_schedules.svc.delete_full_schedule",
        AsyncMock(return_value=None),
    ):
        r = client.delete(
            f"/api/admin/backup-schedules/full/{uuid4()}",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 204


def test_delete_full_404(client: TestClient) -> None:
    from agflow.services.backup_schedules_service import ScheduleNotFoundError
    with patch(
        "agflow.api.admin.backup_schedules.svc.delete_full_schedule",
        AsyncMock(side_effect=ScheduleNotFoundError("nope")),
    ):
        r = client.delete(
            f"/api/admin/backup-schedules/full/{uuid4()}",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 404


def test_run_now_full_returns_202(client: TestClient) -> None:
    with (
        patch(
            "agflow.api.admin.backup_schedules.svc.get_full_schedule",
            AsyncMock(return_value=_full_summary("x")),
        ),
        patch(
            "agflow.api.admin.backup_schedules.backup_scheduler.trigger_now",
            AsyncMock(return_value=None),
        ),
    ):
        r = client.post(
            f"/api/admin/backup-schedules/full/{uuid4()}/run-now",
            headers={"Authorization": f"Bearer {_admin_token()}"},
        )
    assert r.status_code == 202


def test_set_full_enabled_toggles(client: TestClient) -> None:
    with patch(
        "agflow.api.admin.backup_schedules.svc.set_full_enabled",
        AsyncMock(return_value=_full_summary("x", enabled=False)),
    ):
        r = client.post(
            f"/api/admin/backup-schedules/full/{uuid4()}/set-enabled",
            headers={"Authorization": f"Bearer {_admin_token()}"},
            json={"enabled": False},
        )
    assert r.status_code == 200
    assert r.json()["enabled"] is False


def test_post_full_422_empty_destinations(client: TestClient) -> None:
    """POST avec keep_local=false + remote_connection_ids=[] → 422."""
    from agflow.services.backup_schedules_service import EmptyDestinationsError
    with (
        patch(
            "agflow.api.admin.backup_schedules.users_service.get_by_email",
            AsyncMock(return_value=type("U", (), {"id": uuid4()})()),
        ),
        patch(
            "agflow.api.admin.backup_schedules.svc.create_full_schedule",
            AsyncMock(side_effect=EmptyDestinationsError("no dest")),
        ),
    ):
        r = client.post(
            "/api/admin/backup-schedules/full",
            headers={"Authorization": f"Bearer {_admin_token()}"},
            json={
                "name": "bad",
                "cron_expr": "0 3 * * *",
                "remote_connection_ids": [],
                "keep_local": False,
                "retention_count": 10,
                "enabled": True,
            },
        )
    assert r.status_code == 422


def test_post_full_404_unknown_remote(client: TestClient) -> None:
    """POST avec un remote_connection_id inconnu → 404."""
    from agflow.services.backup_schedules_service import RemoteNotFoundError
    with (
        patch(
            "agflow.api.admin.backup_schedules.users_service.get_by_email",
            AsyncMock(return_value=type("U", (), {"id": uuid4()})()),
        ),
        patch(
            "agflow.api.admin.backup_schedules.svc.create_full_schedule",
            AsyncMock(side_effect=RemoteNotFoundError("unknown-uuid")),
        ),
    ):
        r = client.post(
            "/api/admin/backup-schedules/full",
            headers={"Authorization": f"Bearer {_admin_token()}"},
            json={
                "name": "s",
                "cron_expr": "0 3 * * *",
                "remote_connection_ids": ["12345678-1234-1234-1234-123456789abc"],
                "keep_local": True,
                "retention_count": 10,
                "enabled": True,
            },
        )
    assert r.status_code == 404


