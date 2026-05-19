"""Migration 112 — drop backup_schedules_snapshot + source_schedule_snapshot_id."""
from __future__ import annotations

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


async def test_snapshot_table_dropped(fresh_db):
    """Après migration 112, la table backup_schedules_snapshot ne doit plus exister."""
    result = await fresh_db.fetchval(
        "SELECT to_regclass('public.backup_schedules_snapshot')"
    )
    assert result is None, "backup_schedules_snapshot should be dropped by migration 112"


async def test_source_schedule_snapshot_id_column_dropped(fresh_db):
    """Après migration 112, la colonne source_schedule_snapshot_id ne doit plus exister."""
    result = await fresh_db.fetchval(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'local_backups' AND column_name = 'source_schedule_snapshot_id'"
    )
    assert result is None, "local_backups.source_schedule_snapshot_id should be dropped"


async def test_source_schedule_full_id_column_still_exists(fresh_db):
    """Garde-fou : la colonne full (qu'on garde) doit toujours exister."""
    result = await fresh_db.fetchval(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'local_backups' AND column_name = 'source_schedule_full_id'"
    )
    assert result == "source_schedule_full_id"


async def test_local_backups_source_single_constraint_dropped(fresh_db):
    """Le CHECK local_backups_source_single référence la colonne snapshot, doit être dropped."""
    result = await fresh_db.fetchval(
        "SELECT conname FROM pg_constraint WHERE conname = 'local_backups_source_single'"
    )
    assert result is None
