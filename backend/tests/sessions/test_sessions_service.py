from __future__ import annotations

import uuid
from uuid import UUID, uuid4

import pytest
import pytest_asyncio

from agflow.db.pool import close_pool, execute, fetch_one, get_pool
from agflow.services import agents_catalog_service, sessions_service


@pytest_asyncio.fixture
async def pool():
    p = await get_pool()
    yield p
    await close_pool()


@pytest_asyncio.fixture
async def api_key_id(pool) -> UUID:
    kid = uuid4()
    await execute(
        "INSERT INTO api_keys (id, owner_id, name, prefix, key_hash, scopes) "
        "VALUES ($1, $2, 'test', $3, 'hash', $4)",
        kid,
        uuid4(),
        f"pfx_{str(kid)[:8]}",
        ["read"],
    )
    yield kid
    await execute("DELETE FROM api_keys WHERE id = $1", kid)


@pytest.mark.asyncio
class TestSessionsService:
    async def test_create_session_default_duration(self, api_key_id: UUID) -> None:
        session = await sessions_service.create(
            api_key_id=api_key_id,
            name="test",
            duration_seconds=3600,
        )
        assert session["status"] == "active"
        assert session["name"] == "test"
        delta = session["expires_at"] - session["created_at"]
        assert abs(delta.total_seconds() - 3600) < 5
        await sessions_service.close(
            session_id=session["id"],
            api_key_id=api_key_id,
            is_admin=False,
        )

    async def test_get_session_scoped_by_api_key(self, api_key_id: UUID) -> None:
        session = await sessions_service.create(
            api_key_id=api_key_id,
            name=None,
            duration_seconds=3600,
        )
        found = await sessions_service.get(
            session_id=session["id"],
            api_key_id=api_key_id,
            is_admin=False,
        )
        assert found is not None
        assert found["id"] == session["id"]

        other_key = uuid4()
        not_found = await sessions_service.get(
            session_id=session["id"],
            api_key_id=other_key,
            is_admin=False,
        )
        assert not_found is None
        await sessions_service.close(
            session_id=session["id"],
            api_key_id=api_key_id,
            is_admin=False,
        )

    async def test_admin_sees_other_sessions(self, api_key_id: UUID) -> None:
        session = await sessions_service.create(
            api_key_id=api_key_id,
            name=None,
            duration_seconds=3600,
        )
        other_key = uuid4()
        found = await sessions_service.get(
            session_id=session["id"],
            api_key_id=other_key,
            is_admin=True,
        )
        assert found is not None
        await sessions_service.close(
            session_id=session["id"],
            api_key_id=api_key_id,
            is_admin=False,
        )

    async def test_extend_session(self, api_key_id: UUID) -> None:
        session = await sessions_service.create(
            api_key_id=api_key_id,
            name=None,
            duration_seconds=600,
        )
        original_expires = session["expires_at"]
        extended = await sessions_service.extend(
            session_id=session["id"],
            api_key_id=api_key_id,
            is_admin=False,
            additional_seconds=1800,
        )
        assert (extended["expires_at"] - original_expires).total_seconds() >= 1800 - 5
        await sessions_service.close(
            session_id=session["id"],
            api_key_id=api_key_id,
            is_admin=False,
        )

    async def test_extend_rejects_stranger(self, api_key_id: UUID) -> None:
        session = await sessions_service.create(
            api_key_id=api_key_id,
            name=None,
            duration_seconds=600,
        )
        stranger = uuid4()
        result = await sessions_service.extend(
            session_id=session["id"],
            api_key_id=stranger,
            is_admin=False,
            additional_seconds=600,
        )
        assert result is None
        await sessions_service.close(
            session_id=session["id"],
            api_key_id=api_key_id,
            is_admin=False,
        )

    async def test_close_cascades_via_fk(self, api_key_id: UUID) -> None:
        session = await sessions_service.create(
            api_key_id=api_key_id,
            name=None,
            duration_seconds=3600,
        )
        result = await sessions_service.close(
            session_id=session["id"],
            api_key_id=api_key_id,
            is_admin=False,
        )
        assert result is True
        row = await fetch_one(
            "SELECT status, closed_at FROM sessions WHERE id = $1",
            session["id"],
        )
        assert row["status"] == "closed"
        assert row["closed_at"] is not None

    async def test_expire_stale_sessions(self, api_key_id: UUID) -> None:
        session = await sessions_service.create(
            api_key_id=api_key_id,
            name=None,
            duration_seconds=60,
        )
        await execute(
            "UPDATE sessions SET expires_at = now() - interval '1 minute' WHERE id = $1",
            session["id"],
        )
        count = await sessions_service.expire_stale()
        assert count >= 1
        row = await fetch_one(
            "SELECT status FROM sessions WHERE id = $1",
            session["id"],
        )
        assert row["status"] == "expired"

    async def test_list_all_with_counts_returns_agent_count(self) -> None:
        # Self-contained: seed user + api_key + catalog entry (the shared
        # `api_key_id` fixture skips user creation which violates the FK).
        user_id = uuid4()
        await execute(
            "INSERT INTO users (id, email, name, role, status) "
            "VALUES ($1, $2, 'test', 'user', 'active')",
            user_id,
            f"test-{user_id}@example.com",
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
        agent_slug = f"test-slug-{uuid.uuid4().hex[:8]}"
        await agents_catalog_service.upsert(agent_slug)
        try:
            sess = await sessions_service.create(
                api_key_id=kid,
                name="t1",
                duration_seconds=3600,
                project_id="proj-a",
            )
            await execute(
                """
                INSERT INTO agents_instances
                    (session_id, agent_id, labels, mission)
                VALUES ($1, $2, '{}'::jsonb, 'mission test')
                """,
                sess["id"],
                agent_slug,
            )

            rows = await sessions_service.list_all_with_counts()
            row = next(r for r in rows if r["id"] == sess["id"])
            assert row["agent_count"] == 1
            assert row["project_id"] == "proj-a"
            await sessions_service.close(
                session_id=sess["id"],
                api_key_id=kid,
                is_admin=False,
            )
        finally:
            # Order matters: cascade delete sessions (and agents_instances)
            # via api_keys before removing the catalog row they reference.
            await execute("DELETE FROM api_keys WHERE id = $1", kid)
            await execute("DELETE FROM users WHERE id = $1", user_id)
            await agents_catalog_service.delete(agent_slug)
