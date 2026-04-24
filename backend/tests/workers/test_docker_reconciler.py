from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
import pytest_asyncio

from agflow.db.pool import close_pool, execute, fetch_one, get_pool
from agflow.schemas.containers import ContainerInfo
from agflow.services import (
    agents_catalog_service,
    agents_instances_service,
    sessions_service,
)
from agflow.workers.docker_reconciler import run_docker_reconciliation


@pytest_asyncio.fixture
async def pool():
    p = await get_pool()
    yield p
    await close_pool()


@pytest_asyncio.fixture
async def seeded(pool):
    kid = uuid4()
    await execute(
        "INSERT INTO api_keys (id, owner_id, name, prefix, key_hash, scopes) "
        "VALUES ($1, $2, 'reconcile', $3, 'hash', $4)",
        kid,
        uuid4(),
        f"pfx_{str(kid)[:8]}",
        ["read"],
    )
    slug = f"test-agent-{uuid4().hex[:8]}"
    await agents_catalog_service.upsert(slug)
    session = await sessions_service.create(
        api_key_id=kid,
        name=None,
        duration_seconds=3600,
    )
    ids = await agents_instances_service.create(
        session_id=session["id"],
        agent_id=slug,
        count=1,
        labels={},
        mission=None,
    )
    yield {"api_key_id": kid, "slug": slug, "session_id": session["id"], "instance_id": ids[0]}
    await sessions_service.close(
        session_id=session["id"],
        api_key_id=kid,
        is_admin=False,
    )
    await execute("DELETE FROM api_keys WHERE id = $1", kid)
    await agents_catalog_service.delete(slug)


def _make_container(*, container_id: str, name: str, instance_id: str) -> ContainerInfo:
    return ContainerInfo(
        id=container_id,
        name=name,
        dockerfile_id="claude-code",
        image="test:latest",
        status="running",
        created_at=datetime.now(UTC),
        instance_id=instance_id,
    )


@pytest.mark.asyncio
async def test_instance_with_matching_container_is_left_alone(seeded) -> None:
    instance_id: UUID = seeded["instance_id"]
    await execute(
        "UPDATE agents_instances SET last_container_name = $1 WHERE id = $2",
        "cont-ok",
        instance_id,
    )
    containers = [
        _make_container(
            container_id="abc123",
            name="cont-ok",
            instance_id=str(instance_id),
        )
    ]
    calls: list[str] = []

    async def fake_list_running():
        return containers

    async def fake_stop(cid: str) -> None:
        calls.append(cid)

    summary = await run_docker_reconciliation(
        list_running_fn=fake_list_running,
        stop_fn=fake_stop,
    )
    assert summary == {"orphans_stopped": 0, "missing_containers": 0, "ok": True}
    assert calls == []

    row = await fetch_one(
        "SELECT status FROM agents_instances WHERE id = $1",
        instance_id,
    )
    assert row["status"] == "idle"


@pytest.mark.asyncio
async def test_instance_without_container_is_marked_error(seeded) -> None:
    instance_id: UUID = seeded["instance_id"]
    await execute(
        "UPDATE agents_instances SET last_container_name = $1 WHERE id = $2",
        "cont-vanished",
        instance_id,
    )

    async def fake_list_running():
        return []

    async def fake_stop(cid: str) -> None:
        pass

    summary = await run_docker_reconciliation(
        list_running_fn=fake_list_running,
        stop_fn=fake_stop,
    )
    assert summary["missing_containers"] == 1

    row = await fetch_one(
        "SELECT status, error_message FROM agents_instances WHERE id = $1",
        instance_id,
    )
    assert row["status"] == "error"
    assert row["error_message"] == "container disappeared"


@pytest.mark.asyncio
async def test_orphan_container_is_stopped(seeded) -> None:
    # aucune instance_id n'a ce label
    orphan_label = str(uuid4())
    containers = [
        _make_container(
            container_id="orphan-id",
            name="cont-orphan",
            instance_id=orphan_label,
        )
    ]
    calls: list[str] = []

    async def fake_list_running():
        return containers

    async def fake_stop(cid: str) -> None:
        calls.append(cid)

    summary = await run_docker_reconciliation(
        list_running_fn=fake_list_running,
        stop_fn=fake_stop,
    )
    assert summary["orphans_stopped"] == 1
    assert calls == ["orphan-id"]
