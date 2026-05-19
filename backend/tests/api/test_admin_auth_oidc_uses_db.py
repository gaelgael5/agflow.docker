"""Vérifie que les endpoints OIDC de auth.py lisent la DB et non get_settings()."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


def test_mode_endpoint_reads_db(client: TestClient):
    """GET /admin/auth/mode lit auth_config_service.get_config_internal()."""
    fake_cfg = {
        "mode": "keycloak",
        "keycloak_url": "https://kc.x.com",
        "keycloak_realm": "y",
        "keycloak_client_id": "agflow",
        "keycloak_client_secret_ref": "${vault://default:auth/keycloak/client_secret}",
        "vault_name": "default",
        "updated_at": None,
        "updated_by_user_id": None,
    }
    with patch(
        "agflow.api.admin.auth.auth_config_service.get_config_internal",
        new=AsyncMock(return_value=fake_cfg),
    ):
        r = client.get("/api/admin/auth/mode")
    assert r.status_code == 200
    assert r.json() == {"mode": "keycloak"}


def test_oidc_login_uses_db_config(client: TestClient):
    """GET /admin/auth/oidc/login construit l'URL avec les valeurs DB."""
    fake_cfg = {
        "mode": "keycloak",
        "keycloak_url": "https://kc.x.com",
        "keycloak_realm": "yoops",
        "keycloak_client_id": "agflow",
        "keycloak_client_secret_ref": "${vault://default:auth/keycloak/client_secret}",
        "vault_name": "default",
        "updated_at": None,
        "updated_by_user_id": None,
    }
    with patch(
        "agflow.api.admin.auth.auth_config_service.get_config_internal",
        new=AsyncMock(return_value=fake_cfg),
    ):
        r = client.get("/api/admin/auth/oidc/login", follow_redirects=False)
    assert r.status_code in (302, 307)
    location = r.headers["location"]
    assert "kc.x.com" in location
    assert "realms/yoops" in location
    assert "client_id=agflow" in location


def test_oidc_login_rejects_when_keycloak_not_configured(client: TestClient):
    """Si keycloak_url est vide en DB, /oidc/login retourne 400."""
    fake_cfg = {
        "mode": "local",
        "keycloak_url": "",
        "keycloak_realm": "",
        "keycloak_client_id": "",
        "keycloak_client_secret_ref": "",
        "vault_name": "default",
        "updated_at": None,
        "updated_by_user_id": None,
    }
    with patch(
        "agflow.api.admin.auth.auth_config_service.get_config_internal",
        new=AsyncMock(return_value=fake_cfg),
    ):
        r = client.get("/api/admin/auth/oidc/login")
    assert r.status_code == 400
