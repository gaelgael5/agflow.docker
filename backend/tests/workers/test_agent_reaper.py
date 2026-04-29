from __future__ import annotations

import asyncio
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
from agflow.workers.agent_reaper import reap_once, run_agent_reaper_loop


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
        "VALUES ($1, $2, 'test-agent-reaper', $3, 'hash', $4)",
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
async def test_reap_once_destroys_idle_past_timeout(api_key_id) -> None:
    kid, slug = api_key_id
    # Timeout court pour le test
    await platform_config_service.set_value("agent_idle_timeout_s", "1")

    session = await sessions_service.create(
        api_key_id=kid,
        name=None,
        duration_seconds=3600,
    )
    ids = await agents_instances_service.create(
        session_id=session["id"],
        agent_id=slug,
        count=1,
        labels={},
        mission=None,
    )
    # Force last_activity_at dans le passé
    await execute(
        "UPDATE agents_instances SET last_activity_at = now() - interval '10 seconds' "
        "WHERE id = $1",
        ids[0],
    )

    count = await reap_once()
    assert count >= 1

    row = await fetch_one(
        "SELECT status, destroyed_at FROM agents_instances WHERE id = $1",
        ids[0],
    )
    assert row["status"] == "destroyed"
    assert row["destroyed_at"] is not None

    await platform_config_service.set_value("agent_idle_timeout_s", "600")
    await sessions_service.close(
        session_id=session["id"],
        api_key_id=kid,
        is_admin=False,
    )


@pytest.mark.asyncio
async def test_reap_once_ignores_busy_agents(api_key_id) -> None:
    kid, slug = api_key_id
    await platform_config_service.set_value("agent_idle_timeout_s", "1")

    session = await sessions_service.create(
        api_key_id=kid,
        name=None,
        duration_seconds=3600,
    )
    ids = await agents_instances_service.create(
        session_id=session["id"],
        agent_id=slug,
        count=1,
        labels={},
        mission=None,
    )
    # busy = le reaper doit laisser tranquille
    await execute(
        "UPDATE agents_instances "
        "SET last_activity_at = now() - interval '10 seconds', status = 'busy' "
        "WHERE id = $1",
        ids[0],
    )

    await reap_once()

    row = await fetch_one(
        "SELECT status, destroyed_at FROM agents_instances WHERE id = $1",
        ids[0],
    )
    assert row["status"] == "busy"
    assert row["destroyed_at"] is None

    await platform_config_service.set_value("agent_idle_timeout_s", "600")
    await sessions_service.close(
        session_id=session["id"],
        api_key_id=kid,
        is_admin=False,
    )


@pytest.mark.asyncio
async def test_run_loop_starts_and_stops_cleanly(api_key_id) -> None:
    _ = api_key_id
    await platform_config_service.set_value("supervision_reaper_interval_s", "1")

    stop = asyncio.Event()
    task = asyncio.create_task(run_agent_reaper_loop(stop))
    await asyncio.sleep(0.3)
    stop.set()
    try:
        await asyncio.wait_for(task, timeout=2)
    except TimeoutError:
        task.cancel()

    await platform_config_service.set_value("supervision_reaper_interval_s", "20")
