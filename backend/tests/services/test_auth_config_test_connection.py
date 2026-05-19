"""Tests pour auth_config_service.test_connection (httpx mocked)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agflow.schemas.auth_config import AuthTestRequest
from agflow.services import auth_config_service

pytestmark = pytest.mark.asyncio


def _ok_response(status_code: int = 200, json_payload: dict | None = None) -> MagicMock:
    r = MagicMock()
    r.status_code = status_code
    r.text = "" if json_payload is None else str(json_payload)
    r.json = MagicMock(return_value=json_payload or {})
    return r


def _make_async_client(get_resp: MagicMock, post_resp: MagicMock) -> MagicMock:
    """Build a fake httpx.AsyncClient context manager."""
    fake = MagicMock()
    fake.get = AsyncMock(return_value=get_resp)
    fake.post = AsyncMock(return_value=post_resp)
    fake.__aenter__ = AsyncMock(return_value=fake)
    fake.__aexit__ = AsyncMock(return_value=False)
    return fake


async def test_test_connection_happy_path():
    payload = AuthTestRequest(
        keycloak_url="https://kc.example.com",
        keycloak_realm="yoops",
        keycloak_client_id="agflow",
        keycloak_client_secret="secret",
    )
    fake_client = _make_async_client(
        get_resp=_ok_response(200, {"issuer": "https://kc.example.com/realms/yoops"}),
        post_resp=_ok_response(200, {"access_token": "tok", "token_type": "Bearer"}),
    )
    with patch("httpx.AsyncClient", return_value=fake_client):
        result = await auth_config_service.test_connection(payload)

    assert result.ok is True
    assert result.step == "done"
    assert result.discovery_ok is True
    assert result.token_ok is True


async def test_test_connection_discovery_404():
    payload = AuthTestRequest(
        keycloak_url="https://kc.example.com",
        keycloak_realm="missing-realm",
        keycloak_client_id="agflow",
        keycloak_client_secret="secret",
    )
    fake_client = _make_async_client(
        get_resp=_ok_response(404),
        post_resp=_ok_response(200),
    )
    with patch("httpx.AsyncClient", return_value=fake_client):
        result = await auth_config_service.test_connection(payload)

    assert result.ok is False
    assert result.step == "discovery"
    assert result.discovery_ok is False
    assert result.token_ok is False
    assert "404" in result.detail


async def test_test_connection_discovery_network_error():
    payload = AuthTestRequest(
        keycloak_url="https://unreachable.invalid",
        keycloak_realm="y",
        keycloak_client_id="agflow",
        keycloak_client_secret="secret",
    )
    fake_client = MagicMock()
    fake_client.get = AsyncMock(side_effect=httpx.ConnectError("conn refused"))
    fake_client.__aenter__ = AsyncMock(return_value=fake_client)
    fake_client.__aexit__ = AsyncMock(return_value=False)
    with patch("httpx.AsyncClient", return_value=fake_client):
        result = await auth_config_service.test_connection(payload)

    assert result.ok is False
    assert result.step == "discovery"
    assert "unreachable" in result.detail.lower() or "conn refused" in result.detail


async def test_test_connection_token_401():
    payload = AuthTestRequest(
        keycloak_url="https://kc.example.com",
        keycloak_realm="yoops",
        keycloak_client_id="agflow",
        keycloak_client_secret="wrong",
    )
    fake_client = _make_async_client(
        get_resp=_ok_response(200, {"issuer": "x"}),
        post_resp=_ok_response(401, {"error": "invalid_client"}),
    )
    with patch("httpx.AsyncClient", return_value=fake_client):
        result = await auth_config_service.test_connection(payload)

    assert result.ok is False
    assert result.step == "token"
    assert result.discovery_ok is True
    assert result.token_ok is False
    assert "401" in result.detail


async def test_test_connection_no_secret_no_ref():
    """Si pas de secret dans le payload et pas de ref en DB → échec discovery clair."""
    from tests._db_reset import reset_schema_and_migrate
    await reset_schema_and_migrate()

    payload = AuthTestRequest(
        keycloak_url="https://kc.example.com",
        keycloak_realm="yoops",
        keycloak_client_id="agflow",
    )
    result = await auth_config_service.test_connection(payload)
    assert result.ok is False
    assert "secret" in result.detail.lower()


async def test_test_connection_secret_from_vault():
    """Si payload.keycloak_client_secret est vide mais qu'une ref est en DB,
    résout via vault_client.resolve_ref."""
    from agflow.db.pool import execute as _execute
    from tests._db_reset import reset_schema_and_migrate

    await reset_schema_and_migrate()
    await _execute(
        "UPDATE auth_config SET keycloak_client_secret_ref = $1 WHERE id = 1",
        "${vault://default:auth/keycloak/client_secret}",
    )

    payload = AuthTestRequest(
        keycloak_url="https://kc.example.com",
        keycloak_realm="yoops",
        keycloak_client_id="agflow",
    )
    fake_client = _make_async_client(
        get_resp=_ok_response(200, {"issuer": "x"}),
        post_resp=_ok_response(200, {"access_token": "tok"}),
    )
    with patch("httpx.AsyncClient", return_value=fake_client), patch(
        "agflow.services.auth_config_service.vault_client.resolve_ref",
        new=AsyncMock(return_value="actual-secret"),
    ) as mock_resolve:
        result = await auth_config_service.test_connection(payload)

    mock_resolve.assert_called_once_with("${vault://default:auth/keycloak/client_secret}")
    assert result.ok is True
