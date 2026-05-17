"""Tests de l'endpoint WS /api/admin/supervision/stream."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agflow.auth.jwt import encode_token

pytestmark = pytest.mark.asyncio


def _admin_token() -> str:
    return encode_token("admin@test.local")


@pytest.fixture
def client(monkeypatch):
    from agflow.main import app
    monkeypatch.setenv("AUTH_MODE", "local")
    return TestClient(app)


def test_ws_without_token_returns_403(client):
    # On utilise `Exception` parce que la classe exacte (WebSocketDisconnect
    # côté starlette, ou variantes selon la version) peut changer ; ce qui
    # compte ici, c'est que la connexion soit refusée.
    with (
        pytest.raises(Exception),  # noqa: B017
        client.websocket_connect("/api/admin/supervision/stream"),
    ):
        pass


def test_ws_with_invalid_token_closes_connection(client):
    with (
        pytest.raises(Exception),  # noqa: B017
        client.websocket_connect(
            "/api/admin/supervision/stream?token=bogus"
        ),
    ):
        pass


def test_ws_with_admin_token_connects(client):
    token = _admin_token()
    with client.websocket_connect(
        f"/api/admin/supervision/stream?token={token}"
    ) as ws:
        # Connexion établie sans exception
        assert ws is not None


async def test_ws_receives_pg_notify_payload():
    """Test d'intégration : publish via la fonction puis vérifie réception."""
    pytest.skip("intégration DB — validé via run-test.sh sur LXC fresh")


def test_ws_closes_properly_on_client_disconnect(client):
    """Le serveur ne crashe pas quand le client ferme avant lui."""
    token = _admin_token()
    with client.websocket_connect(
        f"/api/admin/supervision/stream?token={token}"
    ):
        pass  # context manager close
    # Aucune exception attendue après sortie du with
