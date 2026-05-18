"""Tests de workflow_provisioning_service après refacto T2."""
from __future__ import annotations

from uuid import uuid4

import pytest

pytestmark = pytest.mark.asyncio


async def test_provision_runtime_inserts_runtime_pending(
    fresh_db, mock_project_with_resources
):
    """provision_runtime crée le runtime avec status='pending' (worker reprendra)."""
    from agflow.services import workflow_provisioning_service as wp

    project_id = mock_project_with_resources["project_id"]
    runtime_id = await wp.provision_runtime(project_id=project_id)

    row = await fresh_db.fetchrow(
        "SELECT status, user_id FROM project_runtimes WHERE id = $1",
        runtime_id,
    )
    assert row is not None
    assert row["status"] == "pending"  # plus de UPDATE deployed sync
    assert row["user_id"] is None  # workflow m2m


async def test_provision_runtime_creates_runtime_instances(
    fresh_db, mock_project_with_resources
):
    """Pour chaque instance template, une row project_runtime_instances est créée."""
    from agflow.services import workflow_provisioning_service as wp

    project_id = mock_project_with_resources["project_id"]
    expected_count = mock_project_with_resources["resources_count"]
    runtime_id = await wp.provision_runtime(project_id=project_id)

    count = await fresh_db.fetchval(
        """
        SELECT COUNT(*) FROM project_runtime_instances
        WHERE project_runtime_id = $1
        """,
        runtime_id,
    )
    assert count == expected_count


async def test_provision_runtime_unknown_project_raises(fresh_db):
    from agflow.services import workflow_provisioning_service as wp

    with pytest.raises(wp.ProjectNotFoundError):
        await wp.provision_runtime(project_id=uuid4())


async def test_get_resources_returns_resource_id_stable_per_runtime(
    fresh_db, mock_project_with_resources
):
    """Le resource_id = project_runtime_instances.id, stable par runtime."""
    from agflow.services import workflow_provisioning_service as wp

    project_id = mock_project_with_resources["project_id"]
    runtime_id_a = await wp.provision_runtime(project_id=project_id)
    runtime_id_b = await wp.provision_runtime(project_id=project_id)

    res_a = await wp.get_resources(runtime_id=runtime_id_a)
    res_b = await wp.get_resources(runtime_id=runtime_id_b)

    # Les resource_id sont distincts entre les 2 runtimes
    ids_a = {r["resource_id"] for r in res_a}
    ids_b = {r["resource_id"] for r in res_b}
    assert ids_a.isdisjoint(ids_b)
    assert len(ids_a) == mock_project_with_resources["resources_count"]
