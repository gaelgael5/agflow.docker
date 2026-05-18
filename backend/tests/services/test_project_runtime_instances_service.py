"""Tests de project_runtime_instances_service."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_create_bulk_inserts_one_row_per_instance(
    fresh_db, mock_runtime_with_instances
):
    """create_bulk insère 1 row par instance template du projet."""
    from agflow.services import project_runtime_instances_service as pri

    runtime_id = mock_runtime_with_instances["runtime_id"]
    instance_ids = mock_runtime_with_instances["instance_ids"]

    created = await pri.create_bulk(
        project_runtime_id=runtime_id,
        instance_ids=instance_ids,
    )
    assert len(created) == len(instance_ids)
    for row in created:
        assert row["provisioning_status"] == "provisioning"
        assert row["project_runtime_id"] == runtime_id
        assert row["instance_id"] in instance_ids


async def test_list_by_runtime(fresh_db, mock_runtime_with_instances):
    from agflow.services import project_runtime_instances_service as pri

    runtime_id = mock_runtime_with_instances["runtime_id"]
    await pri.create_bulk(
        project_runtime_id=runtime_id,
        instance_ids=mock_runtime_with_instances["instance_ids"],
    )
    rows = await pri.list_by_runtime(project_runtime_id=runtime_id)
    assert len(rows) == len(mock_runtime_with_instances["instance_ids"])


async def test_get_by_id(fresh_db, mock_runtime_with_instances):
    from agflow.services import project_runtime_instances_service as pri

    runtime_id = mock_runtime_with_instances["runtime_id"]
    created = await pri.create_bulk(
        project_runtime_id=runtime_id,
        instance_ids=mock_runtime_with_instances["instance_ids"][:1],
    )
    pri_id = created[0]["id"]
    row = await pri.get_by_id(pri_id)
    assert row is not None
    assert row["id"] == pri_id


async def test_mark_status_ready(fresh_db, mock_runtime_with_instances):
    from agflow.services import project_runtime_instances_service as pri

    runtime_id = mock_runtime_with_instances["runtime_id"]
    created = await pri.create_bulk(
        project_runtime_id=runtime_id,
        instance_ids=mock_runtime_with_instances["instance_ids"][:1],
    )
    pri_id = created[0]["id"]
    await pri.mark_status(
        pri_id=pri_id,
        status="ready",
        connection_params={"url": "https://wiki.example.com"},
        setup_steps=[],
    )
    row = await pri.get_by_id(pri_id)
    assert row["provisioning_status"] == "ready"
    assert row["connection_params"] == {"url": "https://wiki.example.com"}


async def test_mark_failed_records_error(
    fresh_db, mock_runtime_with_instances
):
    from agflow.services import project_runtime_instances_service as pri

    runtime_id = mock_runtime_with_instances["runtime_id"]
    created = await pri.create_bulk(
        project_runtime_id=runtime_id,
        instance_ids=mock_runtime_with_instances["instance_ids"][:1],
    )
    pri_id = created[0]["id"]
    await pri.mark_failed(pri_id=pri_id, error_message="jinja var missing: hostname")
    row = await pri.get_by_id(pri_id)
    assert row["provisioning_status"] == "failed"
    assert "jinja var missing" in row["error_message"]
