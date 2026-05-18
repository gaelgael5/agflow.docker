"""Fixtures partagées pour backend/tests/services/."""
from __future__ import annotations

import json
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest_asyncio
from asyncpg import Connection

from agflow.db.pool import get_pool
from tests._db_reset import reset_schema_and_migrate


@pytest_asyncio.fixture
async def fresh_db() -> AsyncIterator[Connection]:
    await reset_schema_and_migrate()
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


@pytest_asyncio.fixture
async def mock_runtime_with_instances(fresh_db: Connection) -> dict:
    """Crée un projet + 1 group + 3 instances + 1 project_runtime.

    Les instances ont des connection_params Jinja non rendus (template brut).
    Retourne {'runtime_id': UUID, 'project_id': UUID, 'instance_ids': [UUID, ...]}.
    """
    project_id = uuid4()
    await fresh_db.execute(
        """
        INSERT INTO projects (id, display_name, description, network)
        VALUES ($1, 'Test PRI Project', 'fixture for project_runtime_instances', 'agflow')
        """,
        project_id,
    )

    group_id = uuid4()
    await fresh_db.execute(
        """
        INSERT INTO groups (id, project_id, name, max_agents)
        VALUES ($1, $2, 'main', 5)
        """,
        group_id,
        project_id,
    )

    instance_ids: list[UUID] = []
    for name in ["wiki", "repo", "docs"]:
        iid = uuid4()
        instance_ids.append(iid)
        raw_params = json.dumps({"url": "https://{{ runtime.short_id }}.example.com/" + name})
        await fresh_db.execute(
            """
            INSERT INTO instances (
                id, group_id, instance_name, catalog_id,
                status, provisioning_status, connection_params
            )
            VALUES ($1, $2, $3, $4, 'active', 'ready', $5::jsonb)
            """,
            iid,
            group_id,
            f"{name}-1",
            name,
            raw_params,
        )

    runtime_id = uuid4()
    await fresh_db.execute(
        """
        INSERT INTO project_runtimes (id, project_id, user_id, status)
        VALUES ($1, $2, NULL, 'pending')
        """,
        runtime_id,
        project_id,
    )

    return {
        "runtime_id": runtime_id,
        "project_id": project_id,
        "instance_ids": instance_ids,
    }
