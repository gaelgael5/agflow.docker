from __future__ import annotations

import os

import pytest

os.environ["DATABASE_URL"] = "postgresql://agflow:agflow_dev@192.168.10.82:5432/agflow"

from agflow.db.pool import close_pool, execute, fetch_one, get_pool  # noqa: E402


@pytest.mark.asyncio
async def test_pool_connect_and_fetch_one() -> None:
    pool = await get_pool()
    assert pool is not None
    row = await fetch_one("SELECT 1 AS n")
    assert row is not None
    assert row["n"] == 1
    await close_pool()


@pytest.mark.asyncio
async def test_execute_creates_and_drops_temp_table() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("CREATE TEMP TABLE t_test (id INT)")
            await conn.execute("INSERT INTO t_test(id) VALUES (1), (2)")
            row = await conn.fetchrow("SELECT COUNT(*) AS c FROM t_test")
            await conn.execute("DROP TABLE t_test")
    assert row is not None
    assert row["c"] == 2
    await close_pool()
