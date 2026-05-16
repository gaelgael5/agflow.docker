"""Tests intégration backup_job_runner.run_full_job (DB + mocks providers)."""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agflow.schemas.backup_schedules import FullScheduleCreate
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


@pytest.mark.asyncio
async def test_run_full_job_happy_path_no_remote(fresh_db: None) -> None:
    """Happy path sans remote : crée backup + record_run ok, pas de push."""
    actor = await _create_admin()
    sched = await svc.create_full_schedule(
        FullScheduleCreate(name="s", cron_expr="0 * * * *", retention_count=5),
        actor_user_id=actor,
    )

    # Mock create_backup pour ne pas vraiment dump Postgres
    fake_backup = MagicMock(id=uuid.uuid4(), filename="b.sql.gz")
    with patch(
        "agflow.services.backup_job_runner.local_backups_service.create_backup",
        AsyncMock(return_value=fake_backup),
    ) as mock_create:
        await backup_job_runner.run_full_job(sched.id)

    mock_create.assert_called_once()
    # Vérifie qu'on passe source_schedule_full_id
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
        FullScheduleCreate(name="s", cron_expr="0 * * * *", enabled=False),
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
    """Avec remote configurée : create + push + record ok."""
    from agflow.db.pool import execute

    actor = await _create_admin()

    # Crée une remote_backup_connection minimale (SFTP fake)
    conn_id = uuid.uuid4()
    await execute(
        "INSERT INTO remote_backup_connections "
        "(id, name, kind, config, vault_api_key_id, vault_secret_path) "
        "VALUES ($1, 'r', 'sftp', '{}'::jsonb, 'default', 'remote-backups/dummy')",
        conn_id,
    )

    sched = await svc.create_full_schedule(
        FullScheduleCreate(
            name="s", cron_expr="0 * * * *",
            remote_connection_id=conn_id,
        ),
        actor_user_id=actor,
    )

    fake_backup = MagicMock(id=uuid.uuid4(), filename="b.sql.gz")
    fake_provider = MagicMock()
    fake_provider.upload_stream = AsyncMock(return_value=42)

    with (
        patch(
            "agflow.services.backup_job_runner.local_backups_service.create_backup",
            AsyncMock(return_value=fake_backup),
        ),
        patch(
            "agflow.services.backup_job_runner.local_backups_service.stream_backup_chunks",
            AsyncMock(return_value=iter([b"data"])),
        ),
        patch(
            "agflow.services.backup_job_runner.rbc_service.fetch_credentials",
            AsyncMock(return_value={"username": "u", "password": "p"}),
        ),
        patch(
            "agflow.services.backup_job_runner.rbc_service.resolve_remote_path",
            return_value="full/",
        ),
        patch(
            "agflow.services.backup_job_runner.get_provider",
            return_value=fake_provider,
        ),
    ):
        await backup_job_runner.run_full_job(sched.id)

    fake_provider.upload_stream.assert_called_once()
    refreshed = await svc.get_full_schedule(sched.id)
    assert refreshed.last_run_status == "ok"


@pytest.mark.asyncio
async def test_run_full_job_remote_push_failed(fresh_db: None) -> None:
    """Backup local OK mais push remote KO → status='failed' avec l'erreur."""
    from agflow.db.pool import execute

    actor = await _create_admin()
    conn_id = uuid.uuid4()
    await execute(
        "INSERT INTO remote_backup_connections "
        "(id, name, kind, config, vault_api_key_id, vault_secret_path) "
        "VALUES ($1, 'r', 'sftp', '{}'::jsonb, 'default', 'remote-backups/dummy')",
        conn_id,
    )

    sched = await svc.create_full_schedule(
        FullScheduleCreate(
            name="s", cron_expr="0 * * * *",
            remote_connection_id=conn_id,
        ),
        actor_user_id=actor,
    )

    fake_backup = MagicMock(id=uuid.uuid4(), filename="b.sql.gz")
    fake_provider = MagicMock()
    fake_provider.upload_stream = AsyncMock(side_effect=RuntimeError("S3 timeout"))

    with (
        patch(
            "agflow.services.backup_job_runner.local_backups_service.create_backup",
            AsyncMock(return_value=fake_backup),
        ),
        patch(
            "agflow.services.backup_job_runner.local_backups_service.stream_backup_chunks",
            AsyncMock(return_value=iter([b"data"])),
        ),
        patch(
            "agflow.services.backup_job_runner.rbc_service.fetch_credentials",
            AsyncMock(return_value={"username": "u", "password": "p"}),
        ),
        patch(
            "agflow.services.backup_job_runner.rbc_service.resolve_remote_path",
            return_value="full/",
        ),
        patch(
            "agflow.services.backup_job_runner.get_provider",
            return_value=fake_provider,
        ),
    ):
        await backup_job_runner.run_full_job(sched.id)

    refreshed = await svc.get_full_schedule(sched.id)
    assert refreshed.last_run_status == "failed"
    assert "S3 timeout" in (refreshed.last_run_error or "")


@pytest.mark.asyncio
async def test_run_full_job_prunes_after_run(fresh_db: None) -> None:
    """retention=2 + 3 backups pré-existants + 1 nouveau créé → prune supprime 2 anciens."""
    from agflow.db.pool import execute, fetch_all

    actor = await _create_admin()
    sched = await svc.create_full_schedule(
        FullScheduleCreate(name="s", cron_expr="0 * * * *", retention_count=2),
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
            "source_schedule_full_id, created_at) "
            "VALUES ($1, 'new.sql.gz', '/nonexistent/new.sql.gz', 'completed', $2, now())",
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
