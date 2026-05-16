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


# ── Snapshot CRUD ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_snapshot_schedule(fresh_db: None) -> None:
    from agflow.schemas.backup_schedules import SnapshotScheduleCreate
    actor = await _create_admin()
    out = await svc.create_snapshot_schedule(
        SnapshotScheduleCreate(
            name="rapide", interval_amount=15, interval_unit="minutes",
            retention_count=20,
        ),
        actor_user_id=actor,
    )
    assert out.name == "rapide"
    assert out.interval_amount == 15
    assert out.interval_unit == "minutes"
    assert out.retention_count == 20
    assert out.enabled is True


@pytest.mark.asyncio
async def test_list_snapshot_schedules(fresh_db: None) -> None:
    from agflow.schemas.backup_schedules import SnapshotScheduleCreate
    actor = await _create_admin()
    await svc.create_snapshot_schedule(
        SnapshotScheduleCreate(name="s1", interval_amount=5, interval_unit="minutes"),
        actor_user_id=actor,
    )
    items = await svc.list_snapshot_schedules()
    assert len(items) == 1
    assert items[0].name == "s1"


@pytest.mark.asyncio
async def test_update_snapshot(fresh_db: None) -> None:
    from agflow.schemas.backup_schedules import SnapshotScheduleCreate, SnapshotScheduleUpdate
    actor = await _create_admin()
    created = await svc.create_snapshot_schedule(
        SnapshotScheduleCreate(name="s", interval_amount=10, interval_unit="minutes"),
        actor_user_id=actor,
    )
    updated = await svc.update_snapshot_schedule(
        created.id, SnapshotScheduleUpdate(interval_amount=30, interval_unit="hours"),
    )
    assert updated.interval_amount == 30
    assert updated.interval_unit == "hours"


@pytest.mark.asyncio
async def test_delete_snapshot(fresh_db: None) -> None:
    from agflow.schemas.backup_schedules import SnapshotScheduleCreate
    actor = await _create_admin()
    created = await svc.create_snapshot_schedule(
        SnapshotScheduleCreate(name="s", interval_amount=10, interval_unit="minutes"),
        actor_user_id=actor,
    )
    await svc.delete_snapshot_schedule(created.id)
    with pytest.raises(svc.ScheduleNotFoundError):
        await svc.get_snapshot_schedule(created.id)


@pytest.mark.asyncio
async def test_set_snapshot_enabled(fresh_db: None) -> None:
    from agflow.schemas.backup_schedules import SnapshotScheduleCreate
    actor = await _create_admin()
    created = await svc.create_snapshot_schedule(
        SnapshotScheduleCreate(name="s", interval_amount=10, interval_unit="minutes"),
        actor_user_id=actor,
    )
    disabled = await svc.set_snapshot_enabled(created.id, False)
    assert disabled.enabled is False


# ── record_run (cross-kind) ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_run_full_updates_last_run_fields(fresh_db: None) -> None:
    from agflow.schemas.backup_schedules import FullScheduleCreate
    actor = await _create_admin()
    created = await svc.create_full_schedule(
        FullScheduleCreate(name="s", cron_expr="0 * * * *"), actor_user_id=actor,
    )
    await svc.record_run(schedule_id=created.id, kind="full", status="ok")
    refreshed = await svc.get_full_schedule(created.id)
    assert refreshed.last_run_status == "ok"
    assert refreshed.last_run_at is not None
    assert refreshed.last_run_error is None


@pytest.mark.asyncio
async def test_record_run_snapshot_failed_with_error(fresh_db: None) -> None:
    from agflow.schemas.backup_schedules import SnapshotScheduleCreate
    actor = await _create_admin()
    created = await svc.create_snapshot_schedule(
        SnapshotScheduleCreate(name="s", interval_amount=10, interval_unit="minutes"),
        actor_user_id=actor,
    )
    await svc.record_run(
        schedule_id=created.id, kind="snapshot",
        status="failed", error="S3 upload timeout",
    )
    refreshed = await svc.get_snapshot_schedule(created.id)
    assert refreshed.last_run_status == "failed"
    assert refreshed.last_run_error == "S3 upload timeout"


# ── prune_old_backups (cross-kind) ─────────────────────────────────────


@pytest.mark.asyncio
async def test_prune_old_backups_keeps_n_latest(fresh_db: None, tmp_path) -> None:
    """Crée 5 local_backups liés à 1 schedule, retention=2, vérifie qu'il reste 2 + fichiers physiques supprimés."""
    from agflow.db.pool import execute
    from agflow.schemas.backup_schedules import FullScheduleCreate

    actor = await _create_admin()
    created = await svc.create_full_schedule(
        FullScheduleCreate(name="s", cron_expr="0 * * * *", retention_count=2),
        actor_user_id=actor,
    )

    # Crée 5 backups liés au schedule + leurs fichiers physiques
    backup_ids = []
    for i in range(5):
        bid = uuid.uuid4()
        backup_ids.append(bid)
        f = tmp_path / f"backup-{i}.sql.gz"
        f.write_bytes(b"dummy")
        await execute(
            "INSERT INTO local_backups "
            "(id, filename, file_path, status, source_schedule_full_id, created_at) "
            "VALUES ($1, $2, $3, 'completed', $4, now() - ($5::int || ' minutes')::interval)",
            bid, f.name, str(f), created.id, 5 - i,  # ordre : 4min, 3min, ..., 0min ago
        )

    pruned = await svc.prune_old_backups(
        schedule_id=created.id, kind="full", retention_count=2,
    )
    assert pruned == 3  # 5 - 2 = 3 supprimés

    # Vérifie que les fichiers les plus vieux sont supprimés (3 premiers de backup_ids)
    for i in range(3):
        f = tmp_path / f"backup-{i}.sql.gz"
        assert not f.exists(), f"backup-{i} fichier devait être supprimé"
    for i in range(3, 5):
        f = tmp_path / f"backup-{i}.sql.gz"
        assert f.exists(), f"backup-{i} fichier devait être préservé"

    # Vérifie DB : 2 rows restantes
    from agflow.db.pool import fetch_all
    remaining = await fetch_all(
        "SELECT id FROM local_backups WHERE source_schedule_full_id = $1",
        created.id,
    )
    assert len(remaining) == 2


@pytest.mark.asyncio
async def test_prune_old_backups_noop_when_under_retention(fresh_db: None, tmp_path) -> None:
    from agflow.db.pool import execute
    from agflow.schemas.backup_schedules import SnapshotScheduleCreate

    actor = await _create_admin()
    created = await svc.create_snapshot_schedule(
        SnapshotScheduleCreate(name="s", interval_amount=5, interval_unit="minutes", retention_count=10),
        actor_user_id=actor,
    )

    # 3 backups, retention=10 → rien à supprimer
    for i in range(3):
        f = tmp_path / f"b-{i}.sql.gz"
        f.write_bytes(b"x")
        await execute(
            "INSERT INTO local_backups (id, filename, file_path, status, source_schedule_snapshot_id) "
            "VALUES ($1, $2, $3, 'completed', $4)",
            uuid.uuid4(), f.name, str(f), created.id,
        )

    pruned = await svc.prune_old_backups(
        schedule_id=created.id, kind="snapshot", retention_count=10,
    )
    assert pruned == 0
