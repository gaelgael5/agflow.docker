"""Tests API admin des secrets plateforme.

Les routes `POST /api/admin/secrets/vault` et `POST /api/admin/secrets/env`
gèrent les deux types de secrets : `vault` (valeur stockée dans Harpocrate,
référencée via `${vault://KEY:NAME}`) ou `env` (valeur en clair en DB,
référencée via `${env://NAME}`).

Les tests utilisent la fixture `vault_mock` pour court-circuiter
Harpocrate (cf. `tests/_vault_mock.py`).
"""
from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from agflow.main import create_app
from tests._db_reset import reset_schema_and_migrate
from tests._vault_mock import vault_mock  # noqa: F401  — fixture injectée


@pytest.fixture
async def async_client() -> AsyncIterator[AsyncClient]:
    await reset_schema_and_migrate()
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    # PAS de close_pool() : cf commentaire dans tests/admin/test_admin_sessions_api.py


async def _auth_header(client: AsyncClient) -> dict[str, str]:
    res = await client.post(
        "/api/admin/auth/login",
        json={"email": "admin@example.com", "password": "correct-password"},
    )
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ─── Auth ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_requires_auth(async_client: AsyncClient) -> None:
    res = await async_client.get("/api/admin/secrets")
    assert res.status_code == 401


# ─── Secret vault (valeur dans Harpocrate) ─────────────────────────────────


@pytest.mark.asyncio
async def test_create_vault_secret_lists_and_reveals(
    async_client: AsyncClient, vault_mock
) -> None:
    headers = await _auth_header(async_client)

    create_res = await async_client.post(
        "/api/admin/secrets/vault",
        headers=headers,
        json={"name": "anthropic_api_key", "value": "sk-ant-xyz"},
    )
    assert create_res.status_code == 201, create_res.text
    body = create_res.json()
    assert body["name"] == "ANTHROPIC_API_KEY"
    assert body["type"] == "vault"
    assert body["has_value"] is True
    assert "value" not in body
    secret_id = body["id"]

    # Listage
    list_res = await async_client.get("/api/admin/secrets", headers=headers)
    assert list_res.status_code == 200
    names = [s["name"] for s in list_res.json()]
    assert "ANTHROPIC_API_KEY" in names

    # Reveal
    reveal_res = await async_client.get(
        f"/api/admin/secrets/{secret_id}/reveal", headers=headers
    )
    assert reveal_res.status_code == 200
    assert reveal_res.json()["value"] == "sk-ant-xyz"

    # Delete (204)
    del_res = await async_client.delete(
        f"/api/admin/secrets/{secret_id}", headers=headers
    )
    assert del_res.status_code == 204

    # Plus dans le listing
    list_res2 = await async_client.get("/api/admin/secrets", headers=headers)
    assert "ANTHROPIC_API_KEY" not in [s["name"] for s in list_res2.json()]


@pytest.mark.asyncio
async def test_create_vault_rejects_duplicate(
    async_client: AsyncClient, vault_mock
) -> None:
    headers = await _auth_header(async_client)

    first = await async_client.post(
        "/api/admin/secrets/vault",
        headers=headers,
        json={"name": "DUP_TEST", "value": "a"},
    )
    assert first.status_code == 201

    second = await async_client.post(
        "/api/admin/secrets/vault",
        headers=headers,
        json={"name": "DUP_TEST", "value": "b"},
    )
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_update_replaces_vault_value(
    async_client: AsyncClient, vault_mock
) -> None:
    headers = await _auth_header(async_client)

    create_res = await async_client.post(
        "/api/admin/secrets/vault",
        headers=headers,
        json={"name": "UPDATE_TEST", "value": "old"},
    )
    secret_id = create_res.json()["id"]

    update_res = await async_client.put(
        f"/api/admin/secrets/{secret_id}",
        headers=headers,
        json={"value": "new"},
    )
    assert update_res.status_code == 204

    reveal = await async_client.get(
        f"/api/admin/secrets/{secret_id}/reveal", headers=headers
    )
    assert reveal.json()["value"] == "new"


# ─── Secret env (valeur en DB) ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_env_secret_is_listed(
    async_client: AsyncClient, vault_mock
) -> None:
    headers = await _auth_header(async_client)

    create_res = await async_client.post(
        "/api/admin/secrets/env",
        headers=headers,
        json={"name": "AGFLOW_DEBUG", "value": "true"},
    )
    assert create_res.status_code == 201, create_res.text
    body = create_res.json()
    assert body["name"] == "AGFLOW_DEBUG"
    assert body["type"] == "env"
    assert body["has_value"] is True


# ─── resolve-status (indicateur 🔴🟠🟢) ────────────────────────────────────


@pytest.mark.asyncio
async def test_resolve_status(async_client: AsyncClient, vault_mock) -> None:
    headers = await _auth_header(async_client)

    # Crée un vault (set avec value) → "ok" attendu
    await async_client.post(
        "/api/admin/secrets/vault",
        headers=headers,
        json={"name": "RESOLVE_OK", "value": "the-value"},
    )
    # Crée un env vide → "empty" attendu. NB: value="" est stocké comme NULL
    # côté DB (via `value or None`), et resolve_all() retourne "" pour ce cas.
    await async_client.post(
        "/api/admin/secrets/env",
        headers=headers,
        json={"name": "RESOLVE_EMPTY", "value": ""},
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
