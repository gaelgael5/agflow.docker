from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
import pytest_asyncio

from agflow.db.pool import close_pool, execute, fetch_one, get_pool
from agflow.services import sessions_service
from agflow.workers.session_expiry import run_expiry_loop


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
        "VALUES ($1, $2, 'test-expiry', $3, 'hash', $4)",
        kid, uuid4(), f"pfx_{str(kid)[:8]}", ["read"],
    )
    yield kid
    await execute("DELETE FROM api_keys WHERE id = $1", kid)


@pytest.mark.asyncio
async def test_expiry_loop_flags_stale_sessions(api_key_id: UUID) -> None:
    session = await sessions_service.create(
        api_key_id=api_key_id, name=None, duration_seconds=60,
    )
    await execute(
        "UPDATE sessions SET expires_at = now() - interval '1 minute' WHERE id = $1",
        session["id"],
    )

    stop = asyncio.Event()
    task = asyncio.create_task(run_expiry_loop(stop))
    await asyncio.sleep(0.5)
    stop.set()
    try:
        await asyncio.wait_for(task, timeout=2)
    except TimeoutError:
        task.cancel()

    row = await fetch_one(
        "SELECT status FROM sessions WHERE id = $1", session["id"],
    )
    assert row["status"] == "expired"
