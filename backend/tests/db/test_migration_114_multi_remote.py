"""Migration 114 — multi-remote backup_schedules_full + push history."""
from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

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


async def test_join_table_exists(fresh_db):
    table = await fresh_db.fetchval(
        "SELECT to_regclass('public.backup_schedule_full_remotes')"
    )
    assert table is not None


async def test_pushes_table_exists(fresh_db):
    table = await fresh_db.fetchval("SELECT to_regclass('public.local_backup_pushes')")
    assert table is not None


async def test_keep_local_column_exists(fresh_db):
    col = await fresh_db.fetchval(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='backup_schedules_full' AND column_name='keep_local'"
    )
    assert col == "keep_local"


async def test_local_file_present_column_exists(fresh_db):
    col = await fresh_db.fetchval(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='local_backups' AND column_name='local_file_present'"
    )
    assert col == "local_file_present"


async def test_remote_connection_id_column_dropped(fresh_db):
    col = await fresh_db.fetchval(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name='backup_schedules_full' AND column_name='remote_connection_id'"
    )
    assert col is None


async def test_keep_local_default_true(fresh_db):
    sid = await fresh_db.fetchval(
        "INSERT INTO backup_schedules_full (name, cron_expr) "
        "VALUES ('test', '0 3 * * *') RETURNING id"
    )
    row = await fresh_db.fetchrow(
        "SELECT keep_local FROM backup_schedules_full WHERE id = $1", sid
    )
    assert row["keep_local"] is True


async def test_pushes_status_check_constraint(fresh_db):
    """CHECK status interdit les valeurs hors enum."""
    bid = await fresh_db.fetchval(
        "INSERT INTO local_backups (filename, file_path, size_bytes, status) "
        "VALUES ('t.dump', '/t', 1, 'ok') RETURNING id"
    )
    rid = await fresh_db.fetchval(
        "INSERT INTO remote_backup_connections (name, kind, config) "
        "VALUES ('test', 'sftp', '{}'::jsonb) RETURNING id"
    )
    with pytest.raises(CheckViolationError):
        await fresh_db.execute(
            "INSERT INTO local_backup_pushes (local_backup_id, remote_connection_id, status) "
            "VALUES ($1, $2, 'invalid')",
            bid, rid,
        )
