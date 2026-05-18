"""Fixtures partagées pour backend/tests/workers/."""
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
async def mock_pending_workflow_runtime(fresh_db: Connection) -> dict:
    """Crée 1 projet + 1 group + 2 instances + 1 project_runtime (user_id=NULL).

    Les instances ont des connection_params Jinja valides.
    Crée aussi les project_runtime_instances en status='provisioning'.
    Retourne {'runtime_id': UUID, 'project_id': UUID, 'instance_ids': [UUID, UUID]}.
    """
    project_id = uuid4()
    await fresh_db.execute(
        """
        INSERT INTO projects (id, display_name, description, network)
        VALUES ($1, 'Test Provisioning Project', 'fixture for provisioning_worker', 'agflow')
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
    for name in ["wiki", "repo"]:
        iid = uuid4()
        instance_ids.append(iid)
        raw_params = json.dumps(
            {"url": "https://{{ runtime.short_id }}.example.com/" + name}
        )
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

    for iid in instance_ids:
        await fresh_db.execute(
            """
            INSERT INTO project_runtime_instances
                (project_runtime_id, instance_id, provisioning_status)
            VALUES ($1, $2, 'provisioning')
            """,
            runtime_id,
            iid,
        )

    return {
        "runtime_id": runtime_id,
        "project_id": project_id,
        "instance_ids": instance_ids,
    }


@pytest_asyncio.fixture
async def mock_pending_workflow_runtime_with_bad_jinja(fresh_db: Connection) -> dict:
    """Même forme que mock_pending_workflow_runtime mais avec une var Jinja invalide.

    Au moins 1 instance a un connection_params qui référence une variable
    inexistante (runtime.nonexistent_var) → JinjaRenderError attendue.
    Retourne {'runtime_id': UUID, 'project_id': UUID, 'instance_ids': [UUID]}.
    """
    project_id = uuid4()
    await fresh_db.execute(
        """
        INSERT INTO projects (id, display_name, description, network)
        VALUES ($1, 'Test Bad Jinja Project', 'fixture with bad jinja', 'agflow')
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

    iid = uuid4()
    bad_params = json.dumps(
        {"url": "https://{{ runtime.nonexistent_var }}.example.com"}
    )
    await fresh_db.execute(
        """
        INSERT INTO instances (
            id, group_id, instance_name, catalog_id,
            status, provisioning_status, connection_params
        )
        VALUES ($1, $2, 'bad-1', 'bad', 'active', 'ready', $3::jsonb)
        """,
        iid,
        group_id,
        bad_params,
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

    await fresh_db.execute(
        """
        INSERT INTO project_runtime_instances
            (project_runtime_id, instance_id, provisioning_status)
        VALUES ($1, $2, 'provisioning')
        """,
        runtime_id,
        iid,
    )

    return {
        "runtime_id": runtime_id,
        "project_id": project_id,
        "instance_ids": [iid],
    }


@pytest_asyncio.fixture
async def mock_pending_workflow_runtime_with_pending_setup(fresh_db: Connection) -> dict:
    """Crée 1 projet + 1 group + 1 instance avec setup_steps non-completed.

    connection_params : simple, pas de Jinja.
    setup_steps : [{"action": "run_init_script", "status": "pending"}]
    → l'instance doit être marquée 'pending_setup' par le worker.
    Retourne {'runtime_id': UUID, 'project_id': UUID, 'instance_ids': [UUID]}.
    """
    project_id = uuid4()
    await fresh_db.execute(
        """
        INSERT INTO projects (id, display_name, description, network)
        VALUES ($1, 'Test Pending Setup Project', 'fixture with pending setup steps', 'agflow')
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

    iid = uuid4()
    simple_params = json.dumps({"url": "https://x.example.com"})
    pending_steps = json.dumps([{"action": "run_init_script", "status": "pending"}])
    await fresh_db.execute(
        """
        INSERT INTO instances (
            id, group_id, instance_name, catalog_id,
            status, provisioning_status, connection_params, setup_steps
        )
        VALUES ($1, $2, 'setup-1', 'setup', 'active', 'ready', $3::jsonb, $4::jsonb)
        """,
        iid,
        group_id,
        simple_params,
        pending_steps,
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

    await fresh_db.execute(
        """
        INSERT INTO project_runtime_instances
            (project_runtime_id, instance_id, provisioning_status)
        VALUES ($1, $2, 'provisioning')
        """,
        runtime_id,
        iid,
    )

    return {
        "runtime_id": runtime_id,
        "project_id": project_id,
        "instance_ids": [iid],
    }


@pytest_asyncio.fixture
async def mock_pending_saas_runtime(fresh_db: Connection) -> dict:
    """Crée 1 projet + 1 group + 1 instance + 1 project_runtime (user_id=<uuid>).

    Le discriminant SaaS est user_id NOT NULL : ce runtime ne doit PAS être
    traité par provisioning_worker (filtré par WHERE user_id IS NULL).
    Retourne {'runtime_id': UUID, 'user_id': UUID}.
    """
    project_id = uuid4()
    await fresh_db.execute(
        """
        INSERT INTO projects (id, display_name, description, network)
        VALUES ($1, 'Test SaaS Project', 'fixture for saas runtime', 'agflow')
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

    iid = uuid4()
    await fresh_db.execute(
        """
        INSERT INTO instances (
            id, group_id, instance_name, catalog_id,
            status, provisioning_status
        )
        VALUES ($1, $2, 'saas-1', 'saas', 'active', 'ready')
        """,
        iid,
        group_id,
    )

    user_id = uuid4()
    runtime_id = uuid4()
    await fresh_db.execute(
        """
        INSERT INTO project_runtimes (id, project_id, user_id, status)
        VALUES ($1, $2, $3, 'pending')
        """,
        runtime_id,
        project_id,
        user_id,
    )

    await fresh_db.execute(
        """
        INSERT INTO project_runtime_instances
            (project_runtime_id, instance_id, provisioning_status)
        VALUES ($1, $2, 'provisioning')
        """,
        runtime_id,
        iid,
    )

    return {
        "runtime_id": runtime_id,
        "user_id": user_id,
    }
