"""Migration 120 — scripts.output_variables JSONB DEFAULT '[]'."""
from __future__ import annotations

import json
from collections.abc import AsyncIterator

import pytest
from asyncpg import Connection

from agflow.db.pool import get_pool
from tests._db_reset import reset_schema_and_migrate

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def fresh_db() -> AsyncIterator[Connection]:
    await reset_schema_and_migrate()
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


async def test_column_exists_with_default_empty_array(fresh_db):
    script_id = await fresh_db.fetchval(
        "INSERT INTO scripts (name, content) VALUES ('s1', '') RETURNING id"
    )
    raw = await fresh_db.fetchval(
        "SELECT output_variables FROM scripts WHERE id = $1", script_id
    )
    # asyncpg renvoie le jsonb sérialisé en str.
    if isinstance(raw, str):
        raw = json.loads(raw)
    assert raw == []


async def test_can_store_output_variables(fresh_db):
    script_id = await fresh_db.fetchval(
        "INSERT INTO scripts (name, content) VALUES ('s2', '') RETURNING id"
    )
    payload = [
        {"name": "HOSTNAME", "description": "Hostname public", "path": "result.hostname"},
        {"name": "SERVICE_URL", "description": "URL interne", "path": "result.service"},
    ]
    await fresh_db.execute(
        "UPDATE scripts SET output_variables = $2::jsonb WHERE id = $1",
        script_id, json.dumps(payload),
    )
    raw = await fresh_db.fetchval(
        "SELECT output_variables FROM scripts WHERE id = $1", script_id
    )
    if isinstance(raw, str):
        raw = json.loads(raw)
    assert raw == payload
