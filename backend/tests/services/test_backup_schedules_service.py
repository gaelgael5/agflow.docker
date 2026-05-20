"""Tests intégration du service backup_schedules (DB réelle, fixture fresh_db)."""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest

from agflow.services import backup_schedules_service
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
        name="daily",
        cron_expr="0 3 * * *",
        retention_count=5,
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
            name="bad",
            cron_expr="not a cron",
            actor_user_id=actor,
        )


@pytest.mark.asyncio
async def test_list_full_schedules_returns_created(fresh_db: None) -> None:
    actor = await _create_admin()
    await svc.create_full_schedule(name="a", cron_expr="0 * * * *", actor_user_id=actor)
    await svc.create_full_schedule(name="b", cron_expr="0 0 * * *", actor_user_id=actor)
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
        name="x", cron_expr="0 * * * *", actor_user_id=actor,
    )
    updated = await svc.update_full_schedule(
        created.id, name="y", retention_count=42,
    )
    assert updated.name == "y"
    assert updated.retention_count == 42


@pytest.mark.asyncio
async def test_update_full_rejects_invalid_cron(fresh_db: None) -> None:
    actor = await _create_admin()
    created = await svc.create_full_schedule(
        name="x", cron_expr="0 * * * *", actor_user_id=actor,
    )
    with pytest.raises(svc.InvalidCronExpressionError):
        await svc.update_full_schedule(created.id, cron_expr="bad cron")


@pytest.mark.asyncio
async def test_delete_full_removes_row(fresh_db: None) -> None:
    actor = await _create_admin()
    created = await svc.create_full_schedule(
        name="x", cron_expr="0 * * * *", actor_user_id=actor,
    )
    await svc.delete_full_schedule(created.id)
    with pytest.raises(svc.ScheduleNotFoundError):
        await svc.get_full_schedule(created.id)


@pytest.mark.asyncio
async def test_set_full_enabled_toggles(fresh_db: None) -> None:
    actor = await _create_admin()
    created = await svc.create_full_schedule(
        name="x", cron_expr="0 * * * *", actor_user_id=actor,
    )
    assert created.enabled is True
    disabled = await svc.set_full_enabled(created.id, False)
    assert disabled.enabled is False


# ── record_run (cross-kind) ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_run_full_updates_last_run_fields(fresh_db: None) -> None:
    actor = await _create_admin()
    created = await svc.create_full_schedule(
        name="s", cron_expr="0 * * * *", actor_user_id=actor,
    )
    await svc.record_run(schedule_id=created.id, kind="full", status="ok")
    refreshed = await svc.get_full_schedule(created.id)
    assert refreshed.last_run_status == "ok"
    assert refreshed.last_run_at is not None
    assert refreshed.last_run_error is None


# ── prune_old_backups ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_prune_old_backups_keeps_n_latest(fresh_db: None, tmp_path) -> None:
    """Crée 5 local_backups liés à 1 schedule, retention=2, vérifie qu'il reste 2 + fichiers physiques supprimés."""
    from agflow.db.pool import execute

    actor = await _create_admin()
    created = await svc.create_full_schedule(
        name="s", cron_expr="0 * * * *", retention_count=2, actor_user_id=actor,
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


# ── Multi-remote : nouvelles validations ──────────────────────────────


@pytest.mark.asyncio
async def test_create_full_schedule_rejects_empty_destinations() -> None:
    """keep_local=False + remote_connection_ids=[] → EmptyDestinationsError (pas de DB)."""
    # La validation des destinations se fait avant tout accès DB : pas besoin de fresh_db.
    with pytest.raises(backup_schedules_service.EmptyDestinationsError):
        await backup_schedules_service.create_full_schedule(
            name="bad",
            cron_expr="0 3 * * *",
            remote_connection_ids=[],
            keep_local=False,
            retention_count=10,
            enabled=True,
            actor_user_id=None,
        )


@pytest.mark.asyncio
async def test_update_full_schedule_replaces_remote_list(fresh_db: None) -> None:
    """update avec remote_connection_ids=[r2] remplace [r1] par [r2]."""
    from agflow.db.pool import fetch_one as db_fetch_one

    r1 = (await db_fetch_one(
        "INSERT INTO remote_backup_connections (name, kind, config) "
        "VALUES ('r1', 'sftp', '{}'::jsonb) RETURNING id"
    ))["id"]
    r2 = (await db_fetch_one(
        "INSERT INTO remote_backup_connections (name, kind, config) "
        "VALUES ('r2', 'sftp', '{}'::jsonb) RETURNING id"
    ))["id"]

    sched = await backup_schedules_service.create_full_schedule(
        name="s",
        cron_expr="0 3 * * *",
        remote_connection_ids=[r1],
        keep_local=True,
        retention_count=10,
        enabled=True,
        actor_user_id=None,
    )
    await backup_schedules_service.update_full_schedule(
        sched.id, remote_connection_ids=[r2]
    )
    refreshed = await backup_schedules_service.get_full_schedule(sched.id)
    assert refreshed.remote_connection_ids == [r2]
