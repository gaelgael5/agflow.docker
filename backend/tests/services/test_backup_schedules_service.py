"""Tests intégration du service backup_schedules (DB réelle, fixture fresh_db)."""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest

from agflow.schemas.backup_schedules import (
    FullScheduleCreate,
    FullScheduleUpdate,
)
from agflow.services import backup_schedules_service as svc
from tests._db_reset import reset_schema_and_migrate


@pytest.fixture
async def fresh_db() -> AsyncIterator[None]:
    await reset_schema_and_migrate()
    yield


async def _create_admin() -> uuid.UUID:
    from agflow.db.pool import execute
    uid = uuid.uuid4()
    await execute(
        "INSERT INTO users (id, email, name, role, status) "
        "VALUES ($1, $2, 'a', 'admin', 'active')",
        uid, f"a-{uid}@x.com",
    )
    return uid


@pytest.mark.asyncio
async def test_create_full_schedule(fresh_db: None) -> None:
    actor = await _create_admin()
    out = await svc.create_full_schedule(
        FullScheduleCreate(name="daily", cron_expr="0 3 * * *", retention_count=5),
        actor_user_id=actor,
    )
    assert out.name == "daily"
    assert out.cron_expr == "0 3 * * *"
    assert out.retention_count == 5
    assert out.enabled is True
    assert out.last_run_at is None


@pytest.mark.asyncio
async def test_create_full_rejects_invalid_cron(fresh_db: None) -> None:
    actor = await _create_admin()
    with pytest.raises(svc.InvalidCronExpressionError):
        await svc.create_full_schedule(
            FullScheduleCreate(name="bad", cron_expr="not a cron"),
            actor_user_id=actor,
        )


@pytest.mark.asyncio
async def test_list_full_schedules_returns_created(fresh_db: None) -> None:
    actor = await _create_admin()
    await svc.create_full_schedule(
        FullScheduleCreate(name="a", cron_expr="0 * * * *"), actor_user_id=actor,
    )
    await svc.create_full_schedule(
        FullScheduleCreate(name="b", cron_expr="0 0 * * *"), actor_user_id=actor,
    )
    items = await svc.list_full_schedules()
    assert len(items) == 2
    assert {i.name for i in items} == {"a", "b"}


@pytest.mark.asyncio
async def test_get_full_schedule_404(fresh_db: None) -> None:
    with pytest.raises(svc.ScheduleNotFoundError):
        await svc.get_full_schedule(uuid.uuid4())


@pytest.mark.asyncio
async def test_update_full_changes_fields(fresh_db: None) -> None:
    actor = await _create_admin()
    created = await svc.create_full_schedule(
        FullScheduleCreate(name="x", cron_expr="0 * * * *"), actor_user_id=actor,
    )
    updated = await svc.update_full_schedule(
        created.id, FullScheduleUpdate(name="y", retention_count=42),
    )
    assert updated.name == "y"
    assert updated.retention_count == 42


@pytest.mark.asyncio
async def test_update_full_rejects_invalid_cron(fresh_db: None) -> None:
    actor = await _create_admin()
    created = await svc.create_full_schedule(
        FullScheduleCreate(name="x", cron_expr="0 * * * *"), actor_user_id=actor,
    )
    with pytest.raises(svc.InvalidCronExpressionError):
        await svc.update_full_schedule(
            created.id, FullScheduleUpdate(cron_expr="bad cron"),
        )


@pytest.mark.asyncio
async def test_delete_full_removes_row(fresh_db: None) -> None:
    actor = await _create_admin()
    created = await svc.create_full_schedule(
        FullScheduleCreate(name="x", cron_expr="0 * * * *"), actor_user_id=actor,
    )
    await svc.delete_full_schedule(created.id)
    with pytest.raises(svc.ScheduleNotFoundError):
        await svc.get_full_schedule(created.id)


@pytest.mark.asyncio
async def test_set_full_enabled_toggles(fresh_db: None) -> None:
    actor = await _create_admin()
    created = await svc.create_full_schedule(
        FullScheduleCreate(name="x", cron_expr="0 * * * *"), actor_user_id=actor,
    )
    assert created.enabled is True
    disabled = await svc.set_full_enabled(created.id, False)
    assert disabled.enabled is False
