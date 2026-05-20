"""Migration 116 — infra_categories.visible_in_machines passe à DEFAULT true."""
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


async def test_default_value_is_true_for_new_rows(fresh_db):
    """Une nouvelle ligne sans valeur explicite hérite désormais de TRUE."""
    await fresh_db.execute(
        "INSERT INTO infra_categories (name) VALUES ('test_default_true')"
    )
    val = await fresh_db.fetchval(
        "SELECT visible_in_machines FROM infra_categories WHERE name = 'test_default_true'"
    )
    assert val is True


async def test_no_seeded_category_remains_false_after_migration(fresh_db):
    """Après application de la suite migrations, aucune catégorie seedée n'est
    encore à FALSE. La migration 116 doit aligner les lignes héritées de
    la 101 qui avait DEFAULT false.
    """
    count_false = await fresh_db.fetchval(
        "SELECT COUNT(*) FROM infra_categories WHERE visible_in_machines = false"
    )
    assert count_false == 0
