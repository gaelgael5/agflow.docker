from __future__ import annotations

import json
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
        f"admin-sessions-{user_id}@example.com",
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
    project_id: str | None = "proj-admin",
) -> tuple[UUID, UUID]:
    sess = await fetch_one(
        """
        INSERT INTO sessions (api_key_id, name, project_id, expires_at)
        VALUES ($1, 't-admin', $2, now() + interval '1 hour')
        RETURNING id
        """,
        api_key_id,
        project_id,
    )
    session_id: UUID = sess["id"]
    inst = await fetch_one(
        """
        INSERT INTO agents_instances (session_id, agent_id, labels, mission)
        VALUES ($1, $2, '{}'::jsonb, 'mission admin')
        RETURNING id
        """,
        session_id,
        agent_slug,
    )
    instance_id: UUID = inst["id"]
    return session_id, instance_id


async def _cleanup(user_id: UUID, api_key_id: UUID, agent_slug: str) -> None:
    # Cascade: api_keys -> sessions -> agents_instances
    await execute("DELETE FROM api_keys WHERE id = $1", api_key_id)
    await execute("DELETE FROM users WHERE id = $1", user_id)
    await agents_catalog_service.delete(agent_slug)


@pytest.mark.asyncio
async def test_admin_list_sessions_returns_agent_count(
    async_client: AsyncClient,
) -> None:
    agent_slug = f"adm-{uuid.uuid4().hex[:8]}"
    user_id, kid = await _seed_user_and_key()
    await agents_catalog_service.upsert(agent_slug)
    try:
        session_id, _ = await _seed_session_with_instance(kid, agent_slug)

        headers = await _auth_header(async_client)
        res = await async_client.get("/api/admin/sessions", headers=headers)
        assert res.status_code == 200, res.text
        payload = res.json()
        assert isinstance(payload, list)
        row = next(r for r in payload if r["id"] == str(session_id))
        assert row["agent_count"] >= 1
        assert row["project_id"] == "proj-admin"
        assert row["api_key_id"] == str(kid)
    finally:
        await _cleanup(user_id, kid, agent_slug)


@pytest.mark.asyncio
async def test_admin_get_session_detail(async_client: AsyncClient) -> None:
    agent_slug = f"adm-{uuid.uuid4().hex[:8]}"
    user_id, kid = await _seed_user_and_key()
    await agents_catalog_service.upsert(agent_slug)
    try:
        session_id, _ = await _seed_session_with_instance(kid, agent_slug)

        headers = await _auth_header(async_client)
        res = await async_client.get(
            f"/api/admin/sessions/{session_id}",
            headers=headers,
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["id"] == str(session_id)
        assert body["status"] == "active"
        assert body["project_id"] == "proj-admin"
    finally:
        await _cleanup(user_id, kid, agent_slug)


@pytest.mark.asyncio
async def test_admin_get_session_404(async_client: AsyncClient) -> None:
    headers = await _auth_header(async_client)
    missing = uuid4()
    res = await async_client.get(
        f"/api/admin/sessions/{missing}",
        headers=headers,
    )
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_admin_list_session_agents(async_client: AsyncClient) -> None:
    agent_slug = f"adm-{uuid.uuid4().hex[:8]}"
    user_id, kid = await _seed_user_and_key()
    await agents_catalog_service.upsert(agent_slug)
    try:
        session_id, instance_id = await _seed_session_with_instance(
            kid,
            agent_slug,
        )

        headers = await _auth_header(async_client)
        res = await async_client.get(
            f"/api/admin/sessions/{session_id}/agents",
            headers=headers,
        )
        assert res.status_code == 200, res.text
        items = res.json()
        assert isinstance(items, list)
        assert len(items) >= 1
        match = next(i for i in items if i["id"] == str(instance_id))
        assert match["agent_id"] == agent_slug
        assert match["mission"] == "mission admin"
        assert match["status"] in ("idle", "busy")
    finally:
        await _cleanup(user_id, kid, agent_slug)


@pytest.mark.asyncio
async def test_admin_list_agent_messages(async_client: AsyncClient) -> None:
    agent_slug = f"adm-{uuid.uuid4().hex[:8]}"
    user_id, kid = await _seed_user_and_key()
    await agents_catalog_service.upsert(agent_slug)
    try:
        session_id, instance_id = await _seed_session_with_instance(
            kid,
            agent_slug,
        )

        # Seed two messages directly in agent_messages (TEXT columns)
        msg_in = uuid4()
        msg_out = uuid4()
        await execute(
            """
            INSERT INTO agent_messages
                (msg_id, session_id, instance_id, direction, kind, payload, source)
            VALUES
                ($1, $2, $3, 'in', 'instruction', $4::jsonb, 'test'),
                ($5, $2, $3, 'out', 'event', $6::jsonb, 'test')
            """,
            msg_in,
            str(session_id),
            str(instance_id),
            json.dumps({"text": "hello"}),
            msg_out,
            json.dumps({"text": "world"}),
        )

        headers = await _auth_header(async_client)
        res = await async_client.get(
            f"/api/admin/sessions/{session_id}/agents/{instance_id}/messages",
            headers=headers,
            params={"limit": 50},
        )
        assert res.status_code == 200, res.text
        items = res.json()
        assert isinstance(items, list)
        ids = {item["msg_id"] for item in items}
        assert str(msg_in) in ids
        assert str(msg_out) in ids
        for item in items:
            assert {"msg_id", "direction", "kind", "payload", "created_at"} <= set(
                item.keys(),
            )

        # Filter by direction
        res_filtered = await async_client.get(
            f"/api/admin/sessions/{session_id}/agents/{instance_id}/messages",
            headers=headers,
            params={"direction": "in", "limit": 50},
        )
        assert res_filtered.status_code == 200
        filtered = res_filtered.json()
        assert all(m["direction"] == "in" for m in filtered)
        assert str(msg_in) in {m["msg_id"] for m in filtered}
    finally:
        await _cleanup(user_id, kid, agent_slug)
