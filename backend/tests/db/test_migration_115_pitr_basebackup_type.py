"""Migration 115 — pitr_config.basebackup_type + full_rebase_cron."""
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


async def test_basebackup_type_column_exists_with_default_diff(fresh_db):
    row = await fresh_db.fetchrow(
        "SELECT basebackup_type, full_rebase_cron, basebackup_cron "
        "FROM pitr_config WHERE id = 1"
    )
    assert row is not None
    assert row["basebackup_type"] == "diff"
    assert row["full_rebase_cron"] == "0 2 * * 0"
    # 115 réaligne aussi basebackup_cron sur un intervalle (toutes les 30 min)
    assert row["basebackup_cron"] == "*/30 * * * *"


async def test_basebackup_type_check_rejects_invalid(fresh_db):
    with pytest.raises(CheckViolationError):
        await fresh_db.execute(
            "UPDATE pitr_config SET basebackup_type = 'invalid' WHERE id = 1"
        )


async def test_basebackup_type_accepts_full_diff_incr(fresh_db):
    for value in ("full", "diff", "incr"):
        await fresh_db.execute(
            "UPDATE pitr_config SET basebackup_type = $1 WHERE id = 1", value
        )
        current = await fresh_db.fetchval(
            "SELECT basebackup_type FROM pitr_config WHERE id = 1"
        )
        assert current == value


async def test_full_rebase_cron_is_text_no_check(fresh_db):
    """No CHECK on cron format — APScheduler validates at app level (cf. _validate_cron)."""
    await fresh_db.execute(
        "UPDATE pitr_config SET full_rebase_cron = '30 4 * * 1' WHERE id = 1"
    )
    val = await fresh_db.fetchval(
        "SELECT full_rebase_cron FROM pitr_config WHERE id = 1"
    )
    assert val == "30 4 * * 1"
