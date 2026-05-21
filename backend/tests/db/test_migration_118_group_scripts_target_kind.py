"""Migration 118 — group_scripts.target_kind + machine_id nullable."""
from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from asyncpg import CheckViolationError, Connection

from agflow.db.pool import get_pool
from tests._db_reset import reset_schema_and_migrate

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def fresh_db() -> AsyncIterator[Connection]:
    await reset_schema_and_migrate()
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


async def test_target_kind_column_exists_with_default(fresh_db):
    """La colonne target_kind a DEFAULT 'fixed_machine' (rétrocompat)."""
    default = await fresh_db.fetchval(
        "SELECT column_default FROM information_schema.columns "
        "WHERE table_name = 'group_scripts' AND column_name = 'target_kind'"
    )
    assert default is not None
    assert "fixed_machine" in default


async def test_machine_id_is_nullable(fresh_db):
    nullable = await fresh_db.fetchval(
        "SELECT is_nullable FROM information_schema.columns "
        "WHERE table_name = 'group_scripts' AND column_name = 'machine_id'"
    )
    assert nullable == "YES"


async def test_check_rejects_fixed_machine_without_machine_id(fresh_db):
    """target_kind='fixed_machine' impose machine_id NON NULL."""
    # Seed minimal : un script et un groupe pour avoir des FK valides.
    script_id = await fresh_db.fetchval(
        "INSERT INTO scripts (name, content) VALUES ('s1', '') RETURNING id"
    )
    project_id = await fresh_db.fetchval(
        "INSERT INTO projects (display_name) VALUES ('p1') RETURNING id"
    )
    group_id = await fresh_db.fetchval(
        "INSERT INTO groups (project_id, name) VALUES ($1, 'g1') RETURNING id",
        project_id,
    )
    with pytest.raises(CheckViolationError):
        await fresh_db.execute(
            "INSERT INTO group_scripts (group_id, script_id, target_kind, timing) "
            "VALUES ($1, $2, 'fixed_machine', 'before')",
            group_id, script_id,
        )


async def test_deployment_host_accepts_null_machine_id(fresh_db):
    """target_kind='deployment_host' autorise machine_id NULL (résolu au runtime)."""
    script_id = await fresh_db.fetchval(
        "INSERT INTO scripts (name, content) VALUES ('s2', '') RETURNING id"
    )
    project_id = await fresh_db.fetchval(
        "INSERT INTO projects (display_name) VALUES ('p2') RETURNING id"
    )
    group_id = await fresh_db.fetchval(
        "INSERT INTO groups (project_id, name) VALUES ($1, 'g2') RETURNING id",
        project_id,
    )
    row_id = await fresh_db.fetchval(
        "INSERT INTO group_scripts (group_id, script_id, target_kind, timing) "
        "VALUES ($1, $2, 'deployment_host', 'after') RETURNING id",
        group_id, script_id,
    )
    assert row_id is not None
    machine_id = await fresh_db.fetchval(
        "SELECT machine_id FROM group_scripts WHERE id = $1", row_id
    )
    assert machine_id is None


async def test_check_rejects_invalid_target_kind(fresh_db):
    script_id = await fresh_db.fetchval(
        "INSERT INTO scripts (name, content) VALUES ('s3', '') RETURNING id"
    )
    project_id = await fresh_db.fetchval(
        "INSERT INTO projects (display_name) VALUES ('p3') RETURNING id"
    )
    group_id = await fresh_db.fetchval(
        "INSERT INTO groups (project_id, name) VALUES ($1, 'g3') RETURNING id",
        project_id,
    )
    with pytest.raises(CheckViolationError):
        await fresh_db.execute(
            "INSERT INTO group_scripts (group_id, script_id, target_kind, timing) "
            "VALUES ($1, $2, 'invalid_kind', 'before')",
            group_id, script_id,
        )
