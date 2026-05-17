"""Tests des endpoints workflow sessions/agents/work/delete."""
from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID, uuid4

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


@pytest.fixture
async def mock_api_key(fresh_db: Connection) -> UUID:
    aid = uuid4()
    await fresh_db.execute(
        """
        INSERT INTO api_keys (id, name, prefix, key_hash, scopes)
        VALUES ($1, 'test', 'agfd_test', 'bcrypt-hash', '{m2m:orchestrate}')
        """,
        aid,
    )
    return aid


@pytest.fixture
async def mock_hmac_key(fresh_db: Connection) -> str:
    """Insère une clé HMAC (encrypted bytea irrelevant for FK tests)."""
    await fresh_db.execute(
        """
        INSERT INTO hmac_keys (key_id, key_value_encrypted, description)
        VALUES ('test-hmac', '\\x00'::bytea, 'test')
        """
    )
    return "test-hmac"


@pytest.fixture
async def mock_session(fresh_db: Connection, mock_api_key: UUID) -> UUID:
    sid = uuid4()
    await fresh_db.execute(
        """
        INSERT INTO sessions (id, api_key_id, expires_at)
        VALUES ($1, $2, now() + interval '1 hour')
        """,
        sid, mock_api_key,
    )
    return sid


@pytest.fixture
async def mock_session_and_agent(
    fresh_db: Connection, mock_session: UUID
) -> tuple[UUID, UUID]:
    aid = uuid4()
    await fresh_db.execute(
        """
        INSERT INTO agents_instances (id, session_id, agent_id, labels)
        VALUES ($1, $2, 'claude-r1', '{}'::jsonb)
        """,
        aid, mock_session,
    )
    return mock_session, aid


@pytest.fixture
async def mock_session_with_runtime(
    fresh_db: Connection, mock_api_key: UUID
) -> dict:
    """Session liée à un project_runtime, avec 1 instance ayant mcp_bindings non vides."""
    project_id = uuid4()
    await fresh_db.execute(
        "INSERT INTO projects (id, display_name, description) VALUES ($1, 'p', '')",
        project_id,
    )
    group_id = uuid4()
    await fresh_db.execute(
        "INSERT INTO groups (id, project_id, name, max_agents) VALUES ($1, $2, 'g', 5)",
        group_id, project_id,
    )
    await fresh_db.execute(
        """
        INSERT INTO instances (
            id, group_id, instance_name, catalog_id, status, mcp_bindings
        )
        VALUES (gen_random_uuid(), $1, 'r1', 'wiki', 'active',
                '[{"server_id":"s1","params":{}}]'::jsonb)
        """,
        group_id,
    )
    runtime_id = uuid4()
    await fresh_db.execute(
        """
        INSERT INTO project_runtimes (id, project_id, status, user_id)
        VALUES ($1, $2, 'deployed', NULL)
        """,
        runtime_id, project_id,
    )
    session_id = uuid4()
    await fresh_db.execute(
        """
        INSERT INTO sessions (id, api_key_id, expires_at, project_runtime_id)
        VALUES ($1, $2, now() + interval '1 hour', $3)
        """,
        session_id, mock_api_key, runtime_id,
    )
    return {"session_id": session_id, "runtime_id": runtime_id}


def _admin_header() -> dict[str, str]:
    return {"Authorization": f"Bearer {encode_token('admin@example.com')}"}


async def test_post_session_with_callback_and_hmac_key(
    fresh_db, mock_api_key, mock_hmac_key, client: TestClient
):
    response = client.post(
        "/api/admin/sessions",
        json={
            "api_key_id": str(mock_api_key),
            "duration_seconds": 3600,
            "callback_url": "https://ag.flow/hooks/abc",
            "callback_hmac_key_id": mock_hmac_key,
        },
        headers=_admin_header(),
    )
    assert response.status_code == 201
    body = response.json()
    assert "session_id" in body


async def test_post_session_with_unknown_hmac_key_returns_422(
    fresh_db, mock_api_key, client: TestClient
):
    response = client.post(
        "/api/admin/sessions",
        json={
            "api_key_id": str(mock_api_key),
            "duration_seconds": 3600,
            "callback_url": "https://ag.flow/hooks/abc",
            "callback_hmac_key_id": "nonexistent",
        },
        headers=_admin_header(),
    )
    assert response.status_code == 422


async def test_post_agents_creates_instances(
    fresh_db, mock_session: UUID, client: TestClient
):
    response = client.post(
        f"/api/admin/sessions/{mock_session}/agents",
        json={"agent_id": "claude-code-r1", "count": 1},
        headers=_admin_header(),
    )
    assert response.status_code == 201
    body = response.json()
    assert len(body["agent_instance_ids"]) == 1


async def test_post_work_creates_task_and_idempotent(
    fresh_db, mock_session_and_agent, client: TestClient
):
    sid, aid = mock_session_and_agent
    cid = str(uuid4())
    r1 = client.post(
        f"/api/admin/sessions/{sid}/agents/{aid}/work",
        json={"_agflow_correlation_id": cid, "instruction": {"text": "do it"}},
        headers=_admin_header(),
    )
    assert r1.status_code == 202
    task_id = r1.json()["task_id"]

    r2 = client.post(
        f"/api/admin/sessions/{sid}/agents/{aid}/work",
        json={"_agflow_correlation_id": cid, "instruction": {"text": "different"}},
        headers=_admin_header(),
    )
    assert r2.status_code == 409
    assert r2.json()["detail"]["task_id"] == task_id


async def test_delete_session_force_true_returns_204(
    fresh_db, mock_session: UUID, client: TestClient
):
    response = client.delete(
        f"/api/admin/sessions/{mock_session}?force=true",
        headers=_admin_header(),
    )
    assert response.status_code == 204
