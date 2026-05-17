"""Tests de POST /api/admin/hmac-keys."""
from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from asyncpg import Connection
from fastapi.testclient import TestClient

from agflow.auth.jwt import encode_token
from agflow.db.pool import get_pool
from tests._db_reset import reset_schema_and_migrate

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def fresh_db() -> AsyncIterator[Connection]:
    await reset_schema_and_migrate()
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


def _admin_header() -> dict[str, str]:
    return {"Authorization": f"Bearer {encode_token('admin@example.com')}"}


async def test_post_hmac_key_returns_201(fresh_db, client: TestClient):
    response = client.post(
        "/api/admin/hmac-keys",
        json={
            "key_id": "test-k1",
            "secret_hex": "0123456789abcdef" * 4,
            "description": "test",
        },
        headers=_admin_header(),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["key_id"] == "test-k1"
    assert body["description"] == "test"


async def test_post_hmac_key_duplicate_returns_409(fresh_db, client: TestClient):
    payload = {
        "key_id": "dup-k1",
        "secret_hex": "0123456789abcdef" * 4,
        "description": "",
    }
    r1 = client.post("/api/admin/hmac-keys", json=payload, headers=_admin_header())
    assert r1.status_code == 201
    r2 = client.post("/api/admin/hmac-keys", json=payload, headers=_admin_header())
    assert r2.status_code == 409
