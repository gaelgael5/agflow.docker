"""Migration 119 — table group_variables (variables globales de groupe)."""
from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from asyncpg import Connection, UniqueViolationError

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
async def sample_group_id(fresh_db):
    project_id = await fresh_db.fetchval(
        "INSERT INTO projects (display_name) VALUES ('p1') RETURNING id"
    )
    return await fresh_db.fetchval(
        "INSERT INTO groups (project_id, name) VALUES ($1, 'g1') RETURNING id",
        project_id,
    )


async def test_table_exists(fresh_db):
    table = await fresh_db.fetchval("SELECT to_regclass('public.group_variables')")
    assert table is not None


async def test_insert_basic(fresh_db, sample_group_id):
    row_id = await fresh_db.fetchval(
        "INSERT INTO group_variables (group_id, name, value, description) "
        "VALUES ($1, 'PUBLIC_HOSTNAME', 'outline.yoops.org', 'Hostname public') "
        "RETURNING id",
        sample_group_id,
    )
    assert row_id is not None
    row = await fresh_db.fetchrow(
        "SELECT name, value, description FROM group_variables WHERE id = $1", row_id
    )
    assert row["name"] == "PUBLIC_HOSTNAME"
    assert row["value"] == "outline.yoops.org"
    assert row["description"] == "Hostname public"


async def test_unique_name_per_group(fresh_db, sample_group_id):
    await fresh_db.execute(
        "INSERT INTO group_variables (group_id, name, value) VALUES ($1, 'FOO', 'a')",
        sample_group_id,
    )
    with pytest.raises(UniqueViolationError):
        await fresh_db.execute(
            "INSERT INTO group_variables (group_id, name, value) VALUES ($1, 'FOO', 'b')",
            sample_group_id,
        )


async def test_same_name_different_groups(fresh_db):
    """Le UNIQUE est sur (group_id, name) : deux groupes peuvent partager un nom."""
    project_id = await fresh_db.fetchval(
        "INSERT INTO projects (display_name) VALUES ('p') RETURNING id"
    )
    g1 = await fresh_db.fetchval(
        "INSERT INTO groups (project_id, name) VALUES ($1, 'g1') RETURNING id",
        project_id,
    )
    g2 = await fresh_db.fetchval(
        "INSERT INTO groups (project_id, name) VALUES ($1, 'g2') RETURNING id",
        project_id,
    )
    await fresh_db.execute(
        "INSERT INTO group_variables (group_id, name, value) VALUES ($1, 'FOO', 'x')",
        g1,
    )
    await fresh_db.execute(
        "INSERT INTO group_variables (group_id, name, value) VALUES ($1, 'FOO', 'y')",
        g2,
    )
    count = await fresh_db.fetchval("SELECT COUNT(*) FROM group_variables")
    assert count == 2


async def test_cascade_delete_with_group(fresh_db, sample_group_id):
    await fresh_db.execute(
        "INSERT INTO group_variables (group_id, name, value) VALUES ($1, 'FOO', 'x')",
        sample_group_id,
    )
    await fresh_db.execute("DELETE FROM groups WHERE id = $1", sample_group_id)
    count = await fresh_db.fetchval(
        "SELECT COUNT(*) FROM group_variables WHERE group_id = $1", sample_group_id
    )
    assert count == 0


async def test_updated_at_trigger(fresh_db, sample_group_id):
    row_id = await fresh_db.fetchval(
        "INSERT INTO group_variables (group_id, name, value) VALUES ($1, 'FOO', 'x') "
        "RETURNING id",
        sample_group_id,
    )
    before = await fresh_db.fetchval(
        "SELECT updated_at FROM group_variables WHERE id = $1", row_id
    )
    await fresh_db.execute(
        "UPDATE group_variables SET value = 'y' WHERE id = $1", row_id
    )
    after = await fresh_db.fetchval(
        "SELECT updated_at FROM group_variables WHERE id = $1", row_id
    )
    assert after > before
