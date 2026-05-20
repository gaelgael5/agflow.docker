"""Tests intégration backup_job_runner.run_full_job (DB + mocks providers)."""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agflow.services import backup_job_runner
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


async def _insert_remote(name: str = "r") -> uuid.UUID:
    from agflow.db.pool import fetch_one
    row = await fetch_one(
        "INSERT INTO remote_backup_connections (name, kind, config) "
        "VALUES ($1, 'sftp', '{}'::jsonb) RETURNING id",
        name,
    )
    return row["id"]


@pytest.mark.asyncio
async def test_run_full_job_happy_path_no_remote(fresh_db: None) -> None:
    """Happy path sans remote : crée backup + record_run ok, pas de push."""
    actor = await _create_admin()
    sched = await svc.create_full_schedule(
        name="s", cron_expr="0 * * * *", retention_count=5,
        actor_user_id=actor,
    )

    fake_backup = MagicMock(id=uuid.uuid4(), filename="b.sql.gz")
    with patch(
        "agflow.services.backup_job_runner.local_backups_service.create_backup",
        AsyncMock(return_value=fake_backup),
    ) as mock_create:
        await backup_job_runner.run_full_job(sched.id)

    mock_create.assert_called_once()
    assert mock_create.call_args.kwargs["source_schedule_full_id"] == sched.id

    refreshed = await svc.get_full_schedule(sched.id)
    assert refreshed.last_run_status == "ok"
    assert refreshed.last_run_at is not None
    assert refreshed.last_run_error is None


@pytest.mark.asyncio
async def test_run_full_job_skipped_if_disabled(fresh_db: None) -> None:
    """Si enabled=false → no-op (pas de create_backup, last_run inchangé)."""
    actor = await _create_admin()
    sched = await svc.create_full_schedule(
        name="s", cron_expr="0 * * * *", enabled=False,
        actor_user_id=actor,
    )

    with patch(
        "agflow.services.backup_job_runner.local_backups_service.create_backup",
        AsyncMock(),
    ) as mock_create:
        await backup_job_runner.run_full_job(sched.id)

    mock_create.assert_not_called()

    refreshed = await svc.get_full_schedule(sched.id)
    assert refreshed.last_run_at is None  # inchangé


@pytest.mark.asyncio
async def test_run_full_job_with_remote_push_ok(fresh_db: None) -> None:
    """Avec remote configurée : create + seed + push_all_pending + record ok."""
    actor = await _create_admin()
    conn_id = await _insert_remote("r1")

    sched = await svc.create_full_schedule(
        name="s", cron_expr="0 * * * *",
        remote_connection_ids=[conn_id],
        actor_user_id=actor,
    )

    fake_backup = MagicMock(id=uuid.uuid4(), filename="b.sql.gz")

    with (
        patch(
            "agflow.services.backup_job_runner.local_backups_service.create_backup",
            AsyncMock(return_value=fake_backup),
        ),
        patch(
            "agflow.services.backup_job_runner.local_backup_pushes_service.seed_pushes",
            new=AsyncMock(),
        ) as mock_seed,
        patch(
            "agflow.services.backup_job_runner.local_backup_pushes_service.push_all_pending",
            new=AsyncMock(return_value=True),
        ) as mock_push_all,
    ):
        await backup_job_runner.run_full_job(sched.id)

    mock_seed.assert_called_once_with(
        backup_id=fake_backup.id,
        remote_ids=[conn_id],
    )
    mock_push_all.assert_called_once_with(backup_id=fake_backup.id)

    refreshed = await svc.get_full_schedule(sched.id)
    assert refreshed.last_run_status == "ok"


@pytest.mark.asyncio
async def test_run_full_job_remote_push_failed(fresh_db: None) -> None:
    """create_backup OK mais push_all_pending retourne False → status='ok' (partial fail
    visible via badges), mais delete_file_only n'est PAS appelé."""
    actor = await _create_admin()
    conn_id = await _insert_remote("r1")

    sched = await svc.create_full_schedule(
        name="s", cron_expr="0 * * * *",
        remote_connection_ids=[conn_id],
        keep_local=False,
        actor_user_id=actor,
    )

    fake_backup = MagicMock(id=uuid.uuid4(), filename="b.sql.gz")

    with (
        patch(
            "agflow.services.backup_job_runner.local_backups_service.create_backup",
            AsyncMock(return_value=fake_backup),
        ),
        patch(
            "agflow.services.backup_job_runner.local_backup_pushes_service.seed_pushes",
            new=AsyncMock(),
        ),
        patch(
            "agflow.services.backup_job_runner.local_backup_pushes_service.push_all_pending",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "agflow.services.backup_job_runner.local_backups_service.delete_file_only",
            new=AsyncMock(),
        ) as mock_delete,
    ):
        await backup_job_runner.run_full_job(sched.id)

    mock_delete.assert_not_called()

    refreshed = await svc.get_full_schedule(sched.id)
    assert refreshed.last_run_status == "ok"


@pytest.mark.asyncio
async def test_run_full_job_prunes_after_run(fresh_db: None) -> None:
    """retention=2 + 3 backups pré-existants + 1 nouveau créé → prune supprime 2 anciens."""
    from agflow.db.pool import execute, fetch_all

    actor = await _create_admin()
    sched = await svc.create_full_schedule(
        name="s", cron_expr="0 * * * *", retention_count=2,
        actor_user_id=actor,
    )

    # Crée 3 backups pré-existants liés au schedule (sans fichier physique pour ce test)
    for i in range(3):
        await execute(
            "INSERT INTO local_backups (id, filename, file_path, status, "
            "source_schedule_full_id, created_at) "
            "VALUES ($1, $2, $3, 'completed', $4, now() - ($5::int || ' minutes')::interval)",
            uuid.uuid4(), f"old-{i}.sql.gz", f"/nonexistent/old-{i}.sql.gz",
            sched.id, 100 - i,
        )

    # Mock create_backup pour qu'il INSERT une vraie row (simule comportement réel)
    async def fake_create_backup(**kwargs):
        bid = uuid.uuid4()
        await execute(
            "INSERT INTO local_backups (id, filename, file_path, status, "
            "source_schedule_full_id, created_at, local_file_present) "
            "VALUES ($1, 'new.sql.gz', '/nonexistent/new.sql.gz', 'completed', $2, now(), true)",
            bid, kwargs["source_schedule_full_id"],
        )
        return MagicMock(id=bid, filename="new.sql.gz")

    with patch(
        "agflow.services.backup_job_runner.local_backups_service.create_backup",
        side_effect=fake_create_backup,
    ):
        await backup_job_runner.run_full_job(sched.id)

    # 4 total - retention 2 = 2 supprimés ; reste 2
    remaining = await fetch_all(
        "SELECT id FROM local_backups WHERE source_schedule_full_id = $1",
        sched.id,
    )
    assert len(remaining) == 2


# ---------------------------------------------------------------------------
# Nouveaux tests multi-remote
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_full_job_multi_remote_happy_path(fresh_db: None) -> None:
    """schedule avec 2 remotes → seed_pushes + push_all_pending OK → record_run('ok')."""
    r1 = await _insert_remote("r1")
    r2 = await _insert_remote("r2")

    sched = await svc.create_full_schedule(
        name="multi", cron_expr="0 3 * * *",
        remote_connection_ids=[r1, r2], keep_local=True,
        retention_count=10, enabled=True, actor_user_id=None,
    )

    fake_backup = MagicMock(id=uuid.uuid4())
    with (
        patch(
            "agflow.services.backup_job_runner.local_backups_service.create_backup",
            new=AsyncMock(return_value=fake_backup),
        ),
        patch(
            "agflow.services.backup_job_runner.local_backup_pushes_service.push_all_pending",
            new=AsyncMock(return_value=True),
        ) as mock_push_all,
        patch(
            "agflow.services.backup_job_runner.local_backup_pushes_service.seed_pushes",
            new=AsyncMock(),
        ) as mock_seed,
        patch(
            "agflow.services.backup_job_runner.local_backups_service.delete_file_only",
            new=AsyncMock(),
        ) as mock_delete,
    ):
        await backup_job_runner.run_full_job(sched.id)

    mock_seed.assert_called_once()
    mock_push_all.assert_called_once()
    mock_delete.assert_not_called()


@pytest.mark.asyncio
async def test_run_full_job_keep_local_false_all_ok_deletes_file(fresh_db: None) -> None:
    """keep_local=false + push_all_pending=True → delete_file_only appelé."""
    r1 = await _insert_remote("r1")
    sched = await svc.create_full_schedule(
        name="no-local", cron_expr="0 3 * * *",
        remote_connection_ids=[r1], keep_local=False,
        retention_count=10, enabled=True, actor_user_id=None,
    )

    backup_id = uuid.uuid4()
    with (
        patch(
            "agflow.services.backup_job_runner.local_backups_service.create_backup",
            new=AsyncMock(return_value=MagicMock(id=backup_id)),
        ),
        patch(
            "agflow.services.backup_job_runner.local_backup_pushes_service.push_all_pending",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "agflow.services.backup_job_runner.local_backup_pushes_service.seed_pushes",
            new=AsyncMock(),
        ),
        patch(
            "agflow.services.backup_job_runner.local_backups_service.delete_file_only",
            new=AsyncMock(),
        ) as mock_delete,
    ):
        await backup_job_runner.run_full_job(sched.id)

    mock_delete.assert_called_once_with(backup_id)


@pytest.mark.asyncio
async def test_run_full_job_keep_local_false_push_fail_keeps_file(fresh_db: None) -> None:
    """keep_local=false + push_all_pending=False (partial fail) → delete_file_only NON appelé."""
    r1 = await _insert_remote("r1")
    sched = await svc.create_full_schedule(
        name="no-local-fail", cron_expr="0 3 * * *",
        remote_connection_ids=[r1], keep_local=False,
        retention_count=10, enabled=True, actor_user_id=None,
    )

    with (
        patch(
            "agflow.services.backup_job_runner.local_backups_service.create_backup",
            new=AsyncMock(return_value=MagicMock(id=uuid.uuid4())),
        ),
        patch(
            "agflow.services.backup_job_runner.local_backup_pushes_service.push_all_pending",
            new=AsyncMock(return_value=False),  # partial fail
        ),
        patch(
            "agflow.services.backup_job_runner.local_backup_pushes_service.seed_pushes",
            new=AsyncMock(),
        ),
        patch(
            "agflow.services.backup_job_runner.local_backups_service.delete_file_only",
            new=AsyncMock(),
        ) as mock_delete,
    ):
        await backup_job_runner.run_full_job(sched.id)

    mock_delete.assert_not_called()  # fichier conservé en cas d'échec partiel
