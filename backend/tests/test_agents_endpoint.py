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
async def client() -> AsyncIterator[AsyncClient]:
    for t in [
        "agent_skills",
        "agent_mcp_servers",
        "agents",
        "skills",
        "mcp_servers",
        "discovery_services",
        "dockerfile_builds",
        "dockerfile_files",
        "dockerfiles",
        "role_documents",
        "roles",
        "secrets",
        "schema_migrations",
    ]:
        await execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    await run_migrations(_MIGRATIONS_DIR)
    await execute(
        "INSERT INTO dockerfiles (id, display_name) VALUES ('claude-code', 'Claude Code')"
    )
    await execute(
        """
        INSERT INTO roles (id, display_name, identity_md)
        VALUES ('senior-dev', 'Senior Dev', 'Tu es un dev senior.')
        """
    )

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c
    await close_pool()


async def _token(c: AsyncClient) -> dict[str, str]:
    res = await c.post(
        "/api/admin/auth/login",
        json={"email": "admin@example.com", "password": "correct-password"},
    )
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


_BASE_PAYLOAD = {
    "slug": "my-agent",
    "display_name": "My Agent",
    "dockerfile_id": "claude-code",
    "role_id": "senior-dev",
}


@pytest.mark.asyncio
async def test_create_list_get(client: AsyncClient) -> None:
    h = await _token(client)

    res = await client.post("/api/admin/agents", headers=h, json=_BASE_PAYLOAD)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["slug"] == "my-agent"
    assert body["image_status"] == "missing"
    agent_id = body["id"]

    listing = await client.get("/api/admin/agents", headers=h)
    assert listing.status_code == 200
    assert any(a["id"] == agent_id for a in listing.json())

    detail = await client.get(f"/api/admin/agents/{agent_id}", headers=h)
    assert detail.status_code == 200
    assert detail.json()["display_name"] == "My Agent"


@pytest.mark.asyncio
async def test_create_duplicate_slug_returns_409(client: AsyncClient) -> None:
    h = await _token(client)
    await client.post("/api/admin/agents", headers=h, json=_BASE_PAYLOAD)
    res = await client.post("/api/admin/agents", headers=h, json=_BASE_PAYLOAD)
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_create_unknown_dockerfile_returns_400(
    client: AsyncClient,
) -> None:
    h = await _token(client)
    payload = {**_BASE_PAYLOAD, "dockerfile_id": "nope"}
    res = await client.post("/api/admin/agents", headers=h, json=payload)
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_update_replaces_fields(client: AsyncClient) -> None:
    h = await _token(client)
    created = await client.post(
        "/api/admin/agents", headers=h, json=_BASE_PAYLOAD
    )
    agent_id = created.json()["id"]

    update = {
        "display_name": "Renamed",
        "description": "updated",
        "dockerfile_id": "claude-code",
        "role_id": "senior-dev",
        "timeout_seconds": 7200,
        "network_mode": "host",
    }
    res = await client.put(
        f"/api/admin/agents/{agent_id}", headers=h, json=update
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["display_name"] == "Renamed"
    assert body["timeout_seconds"] == 7200
    assert body["network_mode"] == "host"


@pytest.mark.asyncio
async def test_duplicate_endpoint(client: AsyncClient) -> None:
    h = await _token(client)
    created = await client.post(
        "/api/admin/agents", headers=h, json=_BASE_PAYLOAD
    )
    agent_id = created.json()["id"]

    res = await client.post(
        f"/api/admin/agents/{agent_id}/duplicate",
        headers=h,
        json={"slug": "my-agent-copy", "display_name": "Copy"},
    )
    assert res.status_code == 201, res.text
    assert res.json()["slug"] == "my-agent-copy"
    assert res.json()["id"] != agent_id


@pytest.mark.asyncio
async def test_delete_endpoint(client: AsyncClient) -> None:
    h = await _token(client)
    created = await client.post(
        "/api/admin/agents", headers=h, json=_BASE_PAYLOAD
    )
    agent_id = created.json()["id"]

    res = await client.delete(f"/api/admin/agents/{agent_id}", headers=h)
    assert res.status_code == 204
    missing = await client.get(f"/api/admin/agents/{agent_id}", headers=h)
    assert missing.status_code == 404


@pytest.mark.asyncio
async def test_config_preview_endpoint(client: AsyncClient) -> None:
    h = await _token(client)
    created = await client.post(
        "/api/admin/agents",
        headers=h,
        json={**_BASE_PAYLOAD, "env_vars": {"LITERAL": "ok"}},
    )
    agent_id = created.json()["id"]

    res = await client.get(
        f"/api/admin/agents/{agent_id}/config-preview", headers=h
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["mcp_json"] == {"mcpServers": {}}
    assert body["tools_json"] == []
    assert "LITERAL=ok" in body["env_file"]
    assert body["image_status"] == "missing"
    assert any("image" in e.lower() for e in body["validation_errors"])
