"""Vérifie la présence et la structure de project_runtime_instances.

Garde-fou : la migration 002 doit être appliquée pour que T2 fonctionne.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

import asyncpg
import pytest
from asyncpg import Connection

from agflow.db.pool import get_pool
from tests._db_reset import reset_schema_and_migrate

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def fresh_db() -> AsyncIterator[Connection]:
    """Reset DB schema then yield a pool-acquired asyncpg connection."""
    await reset_schema_and_migrate()
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


async def test_table_exists(fresh_db):
    row = await fresh_db.fetchrow(
        """
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'project_runtime_instances'
        """
    )
    assert row is not None, "table project_runtime_instances manquante"


async def test_columns_present(fresh_db):
    expected = {
        "id", "project_runtime_id", "instance_id",
        "connection_params", "setup_steps", "provisioning_status",
        "container_id", "service_url", "error_message",
        "created_at", "updated_at",
    }
    rows = await fresh_db.fetch(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'project_runtime_instances'
        """
    )
    found = {r["column_name"] for r in rows}
    missing = expected - found
    assert not missing, f"colonnes manquantes : {missing}"


async def test_check_constraint_provisioning_status(fresh_db):
    """Le CHECK constraint doit rejeter une valeur invalide."""
    # Crée un projet + runtime + group + instance valides pour test FK
    project_id = await fresh_db.fetchval(
        """
        INSERT INTO projects (display_name) VALUES ('test-proj') RETURNING id
        """
    )
    runtime_id_real = await fresh_db.fetchval(
        """
        INSERT INTO project_runtimes (project_id, status, user_id)
        VALUES ($1, 'pending', NULL)
        RETURNING id
        """,
        project_id,
    )
    group_id = await fresh_db.fetchval(
        "INSERT INTO groups (project_id, name) VALUES ($1, 'g1') RETURNING id",
        project_id,
    )
    instance_id = await fresh_db.fetchval(
        """
        INSERT INTO instances (group_id, instance_name, catalog_id)
        VALUES ($1, 'i1', 'cat1') RETURNING id
        """,
        group_id,
    )

    with pytest.raises(asyncpg.CheckViolationError):
        await fresh_db.execute(
            """
            INSERT INTO project_runtime_instances
            (project_runtime_id, instance_id, provisioning_status)
            VALUES ($1, $2, 'invalid_status')
            """,
            runtime_id_real,
            instance_id,
        )
