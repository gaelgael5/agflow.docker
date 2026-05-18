"""Tests de DELETE /api/admin/hmac-keys/{key_id}."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from agflow.auth.jwt import encode_token

pytestmark = pytest.mark.skip(
    reason="TestClient/asyncpg loop mismatch (pattern T1 fix 6bb1006) — "
    "validé via run-test.sh étape 7.9 smoke API curl"
)


@pytest.fixture
def client():
    from agflow.main import app
    return TestClient(app)


def _admin_header() -> dict[str, str]:
    return {"Authorization": f"Bearer {encode_token('admin@test.local')}"}


def test_delete_existing_hmac_key_returns_204(client, fresh_db):
    payload = {
        "key_id": "delete-test-1",
        "secret_hex": "0123456789abcdef" * 4,
        "description": "",
    }
    r1 = client.post("/api/admin/hmac-keys", json=payload, headers=_admin_header())
    assert r1.status_code == 201

    r2 = client.delete(
        "/api/admin/hmac-keys/delete-test-1", headers=_admin_header()
    )
    assert r2.status_code == 204


def test_delete_unknown_hmac_key_returns_404(client, fresh_db):
    r = client.delete(
        "/api/admin/hmac-keys/nonexistent", headers=_admin_header()
    )
    assert r.status_code == 404


def test_delete_idempotent_returns_204(client, fresh_db):
    """2x DELETE sur la même clé : 204 puis 204 (idempotence)."""
    payload = {
        "key_id": "delete-idem",
        "secret_hex": "0123456789abcdef" * 4,
        "description": "",
    }
    client.post("/api/admin/hmac-keys", json=payload, headers=_admin_header())

    r1 = client.delete(
        "/api/admin/hmac-keys/delete-idem", headers=_admin_header()
    )
    r2 = client.delete(
        "/api/admin/hmac-keys/delete-idem", headers=_admin_header()
    )
    assert r1.status_code == 204
    assert r2.status_code == 204  # idempotence : déjà rotated → toujours 204
