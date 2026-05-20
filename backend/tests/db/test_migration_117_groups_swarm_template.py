"""Migration 117 — groups.swarm_template_slug + template_file_types 'docker'."""
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


async def test_docker_file_type_is_seeded(fresh_db):
    row = await fresh_db.fetchrow(
        "SELECT key, label FROM template_file_types WHERE key = 'docker'"
    )
    assert row is not None
    assert row["label"] == "Docker compose / swarm (.docker)"


async def test_swarm_template_slug_column_exists(fresh_db):
    column = await fresh_db.fetchval(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'groups' AND column_name = 'swarm_template_slug'"
    )
    assert column == "swarm_template_slug"


async def test_swarm_template_slug_is_nullable(fresh_db):
    """La colonne doit être nullable : un groupe peut n'avoir qu'un template compose."""
    nullable = await fresh_db.fetchval(
        "SELECT is_nullable FROM information_schema.columns "
        "WHERE table_name = 'groups' AND column_name = 'swarm_template_slug'"
    )
    assert nullable == "YES"
