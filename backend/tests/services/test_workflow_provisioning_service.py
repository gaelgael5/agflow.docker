"""Tests de workflow_provisioning_service."""
from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

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


@pytest.fixture
async def mock_project_with_resources(fresh_db: Connection) -> dict:
    """Crée un projet + 1 group + 2 instances (resources)."""
    project_id = uuid4()
    await fresh_db.execute(
        """
        INSERT INTO projects (id, display_name, description, network)
        VALUES ($1, 'Test Project', 'desc', 'agflow')
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
    for name in ["wiki", "repo"]:
        await fresh_db.execute(
            """
            INSERT INTO instances (
                id, group_id, instance_name, catalog_id, status, provisioning_status
            )
            VALUES (gen_random_uuid(), $1, $2, $3, 'active', 'ready')
            """,
            group_id,
            f"{name}-1",
            name,
        )
    return {"project_id": project_id, "resources_count": 2}


async def test_provision_runtime_inserts_row(
    fresh_db: Connection, mock_project_with_resources: dict
):
    from agflow.services import workflow_provisioning_service as wp

    project_id = mock_project_with_resources["project_id"]
    runtime_id = await wp.provision_runtime(project_id=project_id)

    row = await fresh_db.fetchrow(
        "SELECT status FROM project_runtimes WHERE id = $1",
        runtime_id,
    )
    assert row is not None
    assert row["status"] == "deployed"  # sync simulé


async def test_provision_runtime_unknown_project_raises(fresh_db: Connection):
    from agflow.services import workflow_provisioning_service as wp

    with pytest.raises(wp.ProjectNotFoundError):
        await wp.provision_runtime(project_id=uuid4())


async def test_get_resources_returns_project_instances(
    fresh_db: Connection, mock_project_with_resources: dict
):
    from agflow.services import workflow_provisioning_service as wp

    project_id = mock_project_with_resources["project_id"]
    expected_count = mock_project_with_resources["resources_count"]
    runtime_id = await wp.provision_runtime(project_id=project_id)

    resources = await wp.get_resources(runtime_id=runtime_id)
    assert len(resources) == expected_count
