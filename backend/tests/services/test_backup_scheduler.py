"""Tests unit backup_scheduler (mock AsyncIOScheduler, pas de DB)."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def reset_scheduler_state():
    """Vide l'état global du module entre tests."""
    from agflow.services import backup_scheduler
    backup_scheduler._scheduler = None
    yield
    backup_scheduler._scheduler = None


@pytest.mark.asyncio
async def test_start_creates_scheduler_and_calls_reload() -> None:
    from agflow.services import backup_scheduler

    fake_scheduler = MagicMock()
    fake_scheduler.start = MagicMock()
    fake_scheduler.add_job = MagicMock()

    with (
        patch(
            "agflow.services.backup_scheduler.AsyncIOScheduler",
            return_value=fake_scheduler,
        ),
        patch(
            "agflow.services.backup_scheduler.reload_schedules",
            AsyncMock(),
        ) as mock_reload,
    ):
        await backup_scheduler.start()

    fake_scheduler.start.assert_called_once()
    mock_reload.assert_called_once()
    # Vérifie qu'un job de re-sync périodique est ajouté
    fake_scheduler.add_job.assert_called()


@pytest.mark.asyncio
async def test_stop_shutdowns_scheduler() -> None:
    from agflow.services import backup_scheduler
    fake_scheduler = MagicMock()
    backup_scheduler._scheduler = fake_scheduler
    await backup_scheduler.stop()
    fake_scheduler.shutdown.assert_called_once()
    assert backup_scheduler._scheduler is None


@pytest.mark.asyncio
async def test_reload_schedules_adds_new_jobs_from_db() -> None:
    """Si DB contient un schedule full + un snapshot, scheduler.add_job est appelé 2 fois."""
    from agflow.services import backup_scheduler

    fake_scheduler = MagicMock()
    fake_scheduler.get_jobs.return_value = []  # pas de jobs existants
    backup_scheduler._scheduler = fake_scheduler

    full_id = uuid.uuid4()
    snap_id = uuid.uuid4()
    fake_full = MagicMock(id=full_id, enabled=True, cron_expr="0 * * * *", updated_at=MagicMock())
    fake_snap = MagicMock(id=snap_id, enabled=True, interval_amount=15, interval_unit="minutes", updated_at=MagicMock())

    with (
        patch(
            "agflow.services.backup_scheduler.schedules_svc.list_full_schedules",
            AsyncMock(return_value=[fake_full]),
        ),
        patch(
            "agflow.services.backup_scheduler.schedules_svc.list_snapshot_schedules",
            AsyncMock(return_value=[fake_snap]),
        ),
    ):
        await backup_scheduler.reload_schedules()

    # 2 add_job calls (un pour full, un pour snapshot)
    assert fake_scheduler.add_job.call_count == 2


@pytest.mark.asyncio
async def test_reload_schedules_skips_disabled() -> None:
    from agflow.services import backup_scheduler

    fake_scheduler = MagicMock()
    fake_scheduler.get_jobs.return_value = []
    backup_scheduler._scheduler = fake_scheduler

    fake_full = MagicMock(id=uuid.uuid4(), enabled=False, cron_expr="0 * * * *", updated_at=MagicMock())

    with (
        patch(
            "agflow.services.backup_scheduler.schedules_svc.list_full_schedules",
            AsyncMock(return_value=[fake_full]),
        ),
        patch(
            "agflow.services.backup_scheduler.schedules_svc.list_snapshot_schedules",
            AsyncMock(return_value=[]),
        ),
    ):
        await backup_scheduler.reload_schedules()

    # Aucun add_job (disabled)
    fake_scheduler.add_job.assert_not_called()


@pytest.mark.asyncio
async def test_reload_schedules_removes_orphan_jobs() -> None:
    """Job présent dans APScheduler mais plus en DB → remove_job."""
    from agflow.services import backup_scheduler

    orphan_job = MagicMock(id="full:dead-uuid")
    fake_scheduler = MagicMock()
    fake_scheduler.get_jobs.return_value = [orphan_job]
    backup_scheduler._scheduler = fake_scheduler

    with (
        patch(
            "agflow.services.backup_scheduler.schedules_svc.list_full_schedules",
            AsyncMock(return_value=[]),
        ),
        patch(
            "agflow.services.backup_scheduler.schedules_svc.list_snapshot_schedules",
            AsyncMock(return_value=[]),
        ),
    ):
        await backup_scheduler.reload_schedules()

    fake_scheduler.remove_job.assert_called_once_with("full:dead-uuid")


@pytest.mark.asyncio
async def test_trigger_now_calls_add_job_with_immediate_run() -> None:
    """trigger_now ajoute un job éphémère avec next_run_time=now."""
    from agflow.services import backup_scheduler

    fake_scheduler = MagicMock()
    backup_scheduler._scheduler = fake_scheduler

    schedule_id = uuid.uuid4()
    await backup_scheduler.trigger_now(schedule_id=schedule_id, kind="full")

    fake_scheduler.add_job.assert_called_once()
    # Vérifie que c'est marqué pour exécution immédiate
    call_kwargs = fake_scheduler.add_job.call_args.kwargs
    assert "next_run_time" in call_kwargs
