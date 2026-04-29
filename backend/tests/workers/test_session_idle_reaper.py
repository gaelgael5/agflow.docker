from __future__ import annotations

from uuid import UUID, uuid4

import pytest
import pytest_asyncio

from agflow.db.pool import close_pool, execute, fetch_one, get_pool
from agflow.services import (
    agents_catalog_service,
    agents_instances_service,
    platform_config_service,
    sessions_service,
)
from agflow.workers.session_idle_reaper import reap_once


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
        "VALUES ($1, $2, 'test-session-reaper', $3, 'hash', $4)",
        kid,
        uuid4(),
        f"pfx_{str(kid)[:8]}",
        ["read"],
    )
    slug = f"test-agent-{uuid4().hex[:8]}"
    await agents_catalog_service.upsert(slug)
    yield (kid, slug)
    await execute("DELETE FROM api_keys WHERE id = $1", kid)
    await agents_catalog_service.delete(slug)


@pytest.mark.asyncio
async def test_closes_session_without_agents(api_key_id) -> None:
    kid, _slug = api_key_id
    await platform_config_service.set_value("session_idle_timeout_s", "1")
    session = await sessions_service.create(
        api_key_id=kid,
        name=None,
        duration_seconds=3600,
    )
    # Force created_at dans le passé (donc idle depuis longtemps)
    await execute(
        "UPDATE sessions SET created_at = now() - interval '10 seconds' WHERE id = $1",
        session["id"],
    )

    count = await reap_once()
    assert count >= 1

    row = await fetch_one(
        "SELECT status, closed_at FROM sessions WHERE id = $1",
        session["id"],
    )
    assert row["status"] == "closed"
    assert row["closed_at"] is not None

    await platform_config_service.set_value("session_idle_timeout_s", "120")


@pytest.mark.asyncio
async def test_preserves_session_with_recent_activity(api_key_id) -> None:
    kid, slug = api_key_id
    await platform_config_service.set_value("session_idle_timeout_s", "1")
    session = await sessions_service.create(
        api_key_id=kid,
        name=None,
        duration_seconds=3600,
    )
    await execute(
        "UPDATE sessions SET created_at = now() - interval '10 seconds' WHERE id = $1",
        session["id"],
    )
    # Un agent avec activité récente → doit empêcher la fermeture
    ids = await agents_instances_service.create(
        session_id=session["id"],
        agent_id=slug,
        count=1,
        labels={},
        mission=None,
    )

    await reap_once()

    row = await fetch_one(
        "SELECT status FROM sessions WHERE id = $1",
        session["id"],
    )
    assert row["status"] == "active"

    await platform_config_service.set_value("session_idle_timeout_s", "120")
    await agents_instances_service.destroy(
        session_id=session["id"],
        instance_id=ids[0],
    )
    await sessions_service.close(
        session_id=session["id"],
        api_key_id=kid,
        is_admin=False,
    )


@pytest.mark.asyncio
async def test_closes_session_with_only_stale_agents(api_key_id) -> None:
    kid, slug = api_key_id
    await platform_config_service.set_value("session_idle_timeout_s", "1")
    session = await sessions_service.create(
        api_key_id=kid,
        name=None,
        duration_seconds=3600,
    )
    await execute(
        "UPDATE sessions SET created_at = now() - interval '10 seconds' WHERE id = $1",
        session["id"],
    )
    ids = await agents_instances_service.create(
        session_id=session["id"],
        agent_id=slug,
        count=1,
        labels={},
        mission=None,
    )
    # Agent non-destroyed mais sans activité récente
    await execute(
        "UPDATE agents_instances SET last_activity_at = now() - interval '10 seconds' "
        "WHERE id = $1",
        ids[0],
    )

    count = await reap_once()
    assert count >= 1

    row = await fetch_one(
        "SELECT status FROM sessions WHERE id = $1",
        session["id"],
    )
    assert row["status"] == "closed"

    await platform_config_service.set_value("session_idle_timeout_s", "120")
    await agents_instances_service.destroy(
        session_id=session["id"],
        instance_id=ids[0],
    )
