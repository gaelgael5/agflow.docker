from __future__ import annotations

import pytest_asyncio

from agflow.db.pool import execute, get_pool


@pytest_asyncio.fixture(autouse=True)
async def _cleanup_mom_tables():
    """Wipe the MOM message tables before each MOM test.

    These tests share a DB and use synthetic session_id/instance_id values
    that collide across runs. Without per-test cleanup they accumulate
    messages and assertions like `len(claimed) == 1` see counts from
    previous runs.
    """
    await get_pool()
    await execute("DELETE FROM agent_message_delivery")
    await execute("DELETE FROM agent_messages")
    yield
