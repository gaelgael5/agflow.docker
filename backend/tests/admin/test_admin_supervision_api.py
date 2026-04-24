from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from agflow.db.pool import close_pool, execute, fetch_one
from agflow.main import create_app
from agflow.services import agents_catalog_service


@pytest_asyncio.fixture
async def async_client() -> AsyncIterator[AsyncClient]:
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
    assert res.status_code == 200, res.text
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def _seed_user_and_key() -> tuple[UUID, UUID]:
    user_id = uuid4()
    await execute(
        "INSERT INTO users (id, email, name, role, status) "
        "VALUES ($1, $2, 'test', 'user', 'active')",
        user_id,
        f"admin-sup-{user_id}@example.com",
    )
    kid = uuid4()
    await execute(
        "INSERT INTO api_keys (id, owner_id, name, prefix, key_hash, scopes) "
        "VALUES ($1, $2, 'test', $3, 'hash', $4)",
        kid,
        user_id,
        f"pfx_{str(kid)[:8]}",
        ["read"],
    )
    return user_id, kid


async def _seed_session_with_instance(
    api_key_id: UUID,
    agent_slug: str,
) -> tuple[UUID, UUID]:
    sess = await fetch_one(
        """
        INSERT INTO sessions (api_key_id, name, expires_at)
        VALUES ($1, 't-sup', now() + interval '1 hour')
        RETURNING id
        """,
        api_key_id,
    )
    session_id: UUID = sess["id"]
    inst = await fetch_one(
        """
        INSERT INTO agents_instances (session_id, agent_id, labels, mission)
        VALUES ($1, $2, '{}'::jsonb, 'mission sup')
        RETURNING id
        """,
        session_id,
        agent_slug,
    )
    return session_id, inst["id"]


async def _cleanup(user_id: UUID, api_key_id: UUID, agent_slug: str) -> None:
    await execute("DELETE FROM api_keys WHERE id = $1", api_key_id)
    await execute("DELETE FROM users WHERE id = $1", user_id)
    await agents_catalog_service.delete(agent_slug)


@pytest.mark.asyncio
async def test_supervision_overview_returns_counts(async_client: AsyncClient) -> None:
    agent_slug = f"sup-{uuid.uuid4().hex[:8]}"
    user_id, kid = await _seed_user_and_key()
    await agents_catalog_service.upsert(agent_slug)
    try:
        await _seed_session_with_instance(kid, agent_slug)
        headers = await _auth_header(async_client)
        res = await async_client.get("/api/admin/supervision/overview", headers=headers)
        assert res.status_code == 200, res.text
        body = res.json()
        assert "sessions" in body
        assert "agents" in body
        assert "mom" in body
        assert "containers_running" in body
        assert body["sessions"]["active"] >= 1
        assert body["agents"]["idle"] >= 1
        for key in ("active", "closed", "expired"):
            assert isinstance(body["sessions"][key], int)
        for key in ("idle", "busy", "error", "destroyed_total"):
            assert isinstance(body["agents"][key], int)
    finally:
        await _cleanup(user_id, kid, agent_slug)


@pytest.mark.asyncio
async def test_supervision_list_instances_includes_seeded(
    async_client: AsyncClient,
) -> None:
    agent_slug = f"sup-{uuid.uuid4().hex[:8]}"
    user_id, kid = await _seed_user_and_key()
    await agents_catalog_service.upsert(agent_slug)
    try:
        _session_id, instance_id = await _seed_session_with_instance(kid, agent_slug)
        headers = await _auth_header(async_client)
        res = await async_client.get("/api/admin/supervision/instances", headers=headers)
        assert res.status_code == 200, res.text
        items = res.json()
        ids = {i["id"] for i in items}
        assert str(instance_id) in ids
        match = next(i for i in items if i["id"] == str(instance_id))
        assert match["agent_id"] == agent_slug
        assert match["status"] in ("idle", "busy", "error")
    finally:
        await _cleanup(user_id, kid, agent_slug)


@pytest.mark.asyncio
async def test_supervision_list_instances_filters_by_status(
    async_client: AsyncClient,
) -> None:
    agent_slug = f"sup-{uuid.uuid4().hex[:8]}"
    user_id, kid = await _seed_user_and_key()
    await agents_catalog_service.upsert(agent_slug)
    try:
        _session_id, instance_id = await _seed_session_with_instance(kid, agent_slug)
        await execute(
            "UPDATE agents_instances SET status = 'busy' WHERE id = $1",
            instance_id,
        )
        headers = await _auth_header(async_client)
        res = await async_client.get(
            "/api/admin/supervision/instances",
            headers=headers,
            params={"status": "busy"},
        )
        assert res.status_code == 200
        items = res.json()
        assert all(i["status"] == "busy" for i in items)
        assert str(instance_id) in {i["id"] for i in items}

        res_idle = await async_client.get(
            "/api/admin/supervision/instances",
            headers=headers,
            params={"status": "idle"},
        )
        assert res_idle.status_code == 200
        idle_items = res_idle.json()
        assert str(instance_id) not in {i["id"] for i in idle_items}
    finally:
        await _cleanup(user_id, kid, agent_slug)


@pytest.mark.asyncio
async def test_supervision_list_instances_invalid_status_returns_400(
    async_client: AsyncClient,
) -> None:
    headers = await _auth_header(async_client)
    res = await async_client.get(
        "/api/admin/supervision/instances",
        headers=headers,
        params={"status": "does_not_exist"},
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_supervision_get_instance_detail(async_client: AsyncClient) -> None:
    agent_slug = f"sup-{uuid.uuid4().hex[:8]}"
    user_id, kid = await _seed_user_and_key()
    await agents_catalog_service.upsert(agent_slug)
    try:
        _session_id, instance_id = await _seed_session_with_instance(kid, agent_slug)
        headers = await _auth_header(async_client)
        res = await async_client.get(
            f"/api/admin/supervision/instances/{instance_id}",
            headers=headers,
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["id"] == str(instance_id)
        assert body["agent_id"] == agent_slug
        assert "mom_counts" in body
        assert "recent_messages" in body
        assert isinstance(body["recent_messages"], list)
    finally:
        await _cleanup(user_id, kid, agent_slug)


@pytest.mark.asyncio
async def test_supervision_get_instance_404(async_client: AsyncClient) -> None:
    headers = await _auth_header(async_client)
    missing = uuid4()
    res = await async_client.get(
        f"/api/admin/supervision/instances/{missing}",
        headers=headers,
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_supervision_endpoints_require_admin(async_client: AsyncClient) -> None:
    res = await async_client.get("/api/admin/supervision/overview")
    assert res.status_code in (401, 403)
