"""Tests pour /api/admin/auth-config endpoints."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from agflow.auth.jwt import encode_token
from agflow.schemas.auth_config import AuthConfigOut, AuthTestResult


def _admin_token() -> str:
    return encode_token("admin@example.com", role="admin")


def _viewer_token() -> str:
    return encode_token("viewer@example.com", role="viewer")


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _mk_config_out(**overrides) -> AuthConfigOut:
    from datetime import UTC, datetime
    base = dict(
        mode="local",
        keycloak_url="",
        keycloak_realm="",
        keycloak_client_id="",
        has_secret=False,
        vault_name="default",
        updated_at=datetime.now(UTC),
        updated_by_user_id=None,
    )
    base.update(overrides)
    return AuthConfigOut(**base)


def test_get_auth_config_admin_ok(client: TestClient):
    with patch(
        "agflow.api.admin.auth_config.auth_config_service.get_config",
        new=AsyncMock(return_value=_mk_config_out(mode="keycloak", has_secret=True)),
    ):
        r = client.get("/api/admin/auth-config", headers=_auth(_admin_token()))
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "keycloak"
    assert body["has_secret"] is True
    # Secret ref/value JAMAIS dans la réponse
    assert "keycloak_client_secret_ref" not in body
    assert "keycloak_client_secret" not in body


def test_get_auth_config_viewer_403(client: TestClient):
    r = client.get("/api/admin/auth-config", headers=_auth(_viewer_token()))
    assert r.status_code == 403


def test_get_auth_config_no_token_401(client: TestClient):
    r = client.get("/api/admin/auth-config")
    assert r.status_code == 401


def test_put_auth_config_updates(client: TestClient):
    refreshed = _mk_config_out(mode="keycloak", keycloak_url="https://kc.x.com")
    with patch(
        "agflow.api.admin.auth_config.auth_config_service.update_config",
        new=AsyncMock(return_value=refreshed),
    ):
        r = client.put(
            "/api/admin/auth-config",
            headers=_auth(_admin_token()),
            json={"mode": "keycloak", "keycloak_url": "https://kc.x.com"},
        )
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "keycloak"


def test_put_auth_config_invalid_url_422(client: TestClient):
    from agflow.services.auth_config_service import InvalidUrlError
    with patch(
        "agflow.api.admin.auth_config.auth_config_service.update_config",
        new=AsyncMock(side_effect=InvalidUrlError("bad")),
    ):
        r = client.put(
            "/api/admin/auth-config",
            headers=_auth(_admin_token()),
            json={"keycloak_url": "not-a-url"},
        )
    assert r.status_code == 422


def test_put_auth_config_vault_unknown_404(client: TestClient):
    from agflow.services.auth_config_service import VaultNameUnknownError
    with patch(
        "agflow.api.admin.auth_config.auth_config_service.update_config",
        new=AsyncMock(side_effect=VaultNameUnknownError("nope")),
    ):
        r = client.put(
            "/api/admin/auth-config",
            headers=_auth(_admin_token()),
            json={"vault_name": "nope"},
        )
    assert r.status_code == 404


def test_put_auth_config_viewer_403(client: TestClient):
    r = client.put(
        "/api/admin/auth-config",
        headers=_auth(_viewer_token()),
        json={"mode": "local"},
    )
    assert r.status_code == 403


def test_post_test_returns_200_even_on_failure(client: TestClient):
    """POST /test renvoie toujours 200 ; le statut est dans le payload."""
    fail = AuthTestResult(
        ok=False, step="token", discovery_ok=True, token_ok=False,
        detail="HTTP 401 invalid_client",
    )
    with patch(
        "agflow.api.admin.auth_config.auth_config_service.test_connection",
        new=AsyncMock(return_value=fail),
    ):
        r = client.post(
            "/api/admin/auth-config/test",
            headers=_auth(_admin_token()),
            json={
                "keycloak_url": "https://kc.x.com",
                "keycloak_realm": "y",
                "keycloak_client_id": "a",
                "keycloak_client_secret": "s",
            },
        )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["step"] == "token"


def test_post_test_viewer_403(client: TestClient):
    r = client.post(
        "/api/admin/auth-config/test",
        headers=_auth(_viewer_token()),
        json={
            "keycloak_url": "https://kc.x.com",
            "keycloak_realm": "y",
            "keycloak_client_id": "a",
            "keycloak_client_secret": "s",
        },
    )
    assert r.status_code == 403
