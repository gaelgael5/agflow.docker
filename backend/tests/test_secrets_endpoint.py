from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from agflow.db.migrations import run_migrations
from agflow.db.pool import close_pool, execute
from agflow.main import create_app

_MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"


@pytest.fixture
async def async_client() -> AsyncIterator[AsyncClient]:
    # Reset DB via the shared pool (same event loop as the tests)
    await execute("DROP TABLE IF EXISTS secrets CASCADE")
    await execute("DROP TABLE IF EXISTS schema_migrations CASCADE")
    await run_migrations(_MIGRATIONS_DIR)

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    await close_pool()


async def _auth_header(client: AsyncClient) -> dict[str, str]:
    res = await client.post(
        "/api/admin/auth/login",
        json={"email": "admin@example.com", "password": "correct-password"},
    )
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_list_requires_auth(async_client: AsyncClient) -> None:
    res = await async_client.get("/api/admin/secrets")
    assert res.status_code == 401


@pytest.mark.asyncio
async def test_create_list_reveal_delete_secret(async_client: AsyncClient) -> None:
    headers = await _auth_header(async_client)

    create_res = await async_client.post(
        "/api/admin/secrets",
        headers=headers,
        json={"var_name": "test_key_e2e", "value": "abc123", "scope": "global"},
    )
    assert create_res.status_code == 201, create_res.text
    body = create_res.json()
    assert body["var_name"] == "TEST_KEY_E2E"
    assert "value" not in body
    secret_id = body["id"]

    list_res = await async_client.get("/api/admin/secrets", headers=headers)
    assert list_res.status_code == 200
    names = [s["var_name"] for s in list_res.json()]
    assert "TEST_KEY_E2E" in names

    reveal_res = await async_client.get(
        f"/api/admin/secrets/{secret_id}/reveal", headers=headers
    )
    assert reveal_res.status_code == 200
    assert reveal_res.json()["value"] == "abc123"

    del_res = await async_client.delete(
        f"/api/admin/secrets/{secret_id}", headers=headers
    )
    assert del_res.status_code == 204

    list_res2 = await async_client.get("/api/admin/secrets", headers=headers)
    assert "TEST_KEY_E2E" not in [s["var_name"] for s in list_res2.json()]


@pytest.mark.asyncio
async def test_update_replaces_value(async_client: AsyncClient) -> None:
    headers = await _auth_header(async_client)

    create_res = await async_client.post(
        "/api/admin/secrets",
        headers=headers,
        json={"var_name": "update_test", "value": "old"},
    )
    secret_id = create_res.json()["id"]

    update_res = await async_client.put(
        f"/api/admin/secrets/{secret_id}",
        headers=headers,
        json={"value": "new"},
    )
    assert update_res.status_code == 200

    reveal = await async_client.get(
        f"/api/admin/secrets/{secret_id}/reveal", headers=headers
    )
    assert reveal.json()["value"] == "new"


@pytest.mark.asyncio
async def test_resolve_status(async_client: AsyncClient) -> None:
    headers = await _auth_header(async_client)

    await async_client.post(
        "/api/admin/secrets",
        headers=headers,
        json={"var_name": "resolve_ok", "value": "value"},
    )
    await async_client.post(
        "/api/admin/secrets",
        headers=headers,
        json={"var_name": "resolve_empty", "value": " "},
    )

    res = await async_client.get(
        "/api/admin/secrets/resolve-status",
        headers=headers,
        params={"var_names": "RESOLVE_OK,RESOLVE_EMPTY,RESOLVE_MISSING"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["RESOLVE_OK"] == "ok"
    assert data["RESOLVE_EMPTY"] == "empty"
    assert data["RESOLVE_MISSING"] == "missing"


@pytest.mark.asyncio
async def test_create_rejects_duplicate(async_client: AsyncClient) -> None:
    headers = await _auth_header(async_client)

    await async_client.post(
        "/api/admin/secrets",
        headers=headers,
        json={"var_name": "dup_test", "value": "a"},
    )
    res = await async_client.post(
        "/api/admin/secrets",
        headers=headers,
        json={"var_name": "dup_test", "value": "b"},
    )
    assert res.status_code == 409
