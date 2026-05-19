"""Tests pour /api/admin/pitr/config endpoints (GET + PUT)."""
from __future__ import annotations

import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

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
