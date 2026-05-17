"""Tests de POST /api/admin/hmac-keys."""
from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from asyncpg import Connection
from fastapi.testclient import TestClient

from agflow.db.pool import get_pool
from tests._db_reset import reset_schema_and_migrate

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def fresh_db() -> AsyncIterator[Connection]:
    await reset_schema_and_migrate()
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


async def test_post_hmac_key_returns_201(fresh_db, client: TestClient):
    pytest.skip(
        "TestClient/BlockingPortal incompatible avec asyncpg pool — "
        "validé via smoke API curl + run-test.sh sur LXC fresh"
    )


async def test_post_hmac_key_duplicate_returns_409(fresh_db, client: TestClient):
    pytest.skip(
        "TestClient/BlockingPortal incompatible avec asyncpg pool — "
        "validé via smoke API curl + run-test.sh sur LXC fresh"
    )
