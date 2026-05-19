"""Tests pour pitr_scheduler — mock APScheduler."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agflow.services import pitr_scheduler

pytestmark = pytest.mark.asyncio


def _make_fake_config(*, enabled: bool = True, cron: str = "0 3 * * *"):
    cfg = MagicMock()
    cfg.enabled = enabled
    cfg.basebackup_cron = cron
    cfg.retention_count = 7
    cfg.remote_connection_ids = []
    return cfg


async def test_start_creates_three_jobs_when_config_enabled():
    fake_scheduler = MagicMock()
    fake_scheduler.add_job = MagicMock()
    fake_scheduler.start = MagicMock()

    with patch(
        "agflow.services.pitr_scheduler.AsyncIOScheduler",
        return_value=fake_scheduler,
    ), patch(
        "agflow.services.pitr_scheduler.pitr_config_service.get_config",
        new=AsyncMock(return_value=_make_fake_config(enabled=True)),
    ):
        # Ensure module-level _scheduler is reset
        pitr_scheduler._scheduler = None
        await pitr_scheduler.start()

    job_ids = [c.kwargs.get("id") for c in fake_scheduler.add_job.call_args_list]
    assert pitr_scheduler.JOB_BASEBACKUP in job_ids
    assert pitr_scheduler.JOB_CLEANUP in job_ids
    assert pitr_scheduler.JOB_WAL_REFRESH in job_ids
    assert fake_scheduler.start.call_count == 1

    # Reset for next test
    await pitr_scheduler.stop()


async def test_start_skips_basebackup_job_when_disabled():
    fake_scheduler = MagicMock()
    fake_scheduler.add_job = MagicMock()
    fake_scheduler.start = MagicMock()

    with patch(
        "agflow.services.pitr_scheduler.AsyncIOScheduler",
        return_value=fake_scheduler,
    ), patch(
        "agflow.services.pitr_scheduler.pitr_config_service.get_config",
        new=AsyncMock(return_value=_make_fake_config(enabled=False)),
    ):
        pitr_scheduler._scheduler = None
        await pitr_scheduler.start()

    job_ids = [c.kwargs.get("id") for c in fake_scheduler.add_job.call_args_list]
    assert pitr_scheduler.JOB_BASEBACKUP not in job_ids
    assert pitr_scheduler.JOB_CLEANUP in job_ids
    assert pitr_scheduler.JOB_WAL_REFRESH in job_ids

    await pitr_scheduler.stop()


async def test_start_idempotent():
    """Calling start() twice is a no-op the second time."""
    fake_scheduler = MagicMock()
    with patch(
        "agflow.services.pitr_scheduler.AsyncIOScheduler",
        return_value=fake_scheduler,
    ), patch(
        "agflow.services.pitr_scheduler.pitr_config_service.get_config",
        new=AsyncMock(return_value=_make_fake_config(enabled=True)),
    ):
        pitr_scheduler._scheduler = None
        await pitr_scheduler.start()
        first_calls = fake_scheduler.add_job.call_count
        await pitr_scheduler.start()
        # No new jobs added on 2nd call
        assert fake_scheduler.add_job.call_count == first_calls

    await pitr_scheduler.stop()


async def test_reload_basebackup_schedule_replaces_job():
    fake_scheduler = MagicMock()
    fake_scheduler.add_job = MagicMock()
    fake_scheduler.remove_job = MagicMock()
    pitr_scheduler._scheduler = fake_scheduler

    with patch(
        "agflow.services.pitr_scheduler.pitr_config_service.get_config",
        new=AsyncMock(return_value=_make_fake_config(enabled=True, cron="0 4 * * *")),
    ):
        await pitr_scheduler.reload_basebackup_schedule()

    fake_scheduler.remove_job.assert_called_with(pitr_scheduler.JOB_BASEBACKUP)
    added = [c.kwargs.get("id") for c in fake_scheduler.add_job.call_args_list]
    assert pitr_scheduler.JOB_BASEBACKUP in added

    pitr_scheduler._scheduler = None  # reset


async def test_reload_basebackup_schedule_skips_add_when_disabled():
    fake_scheduler = MagicMock()
    fake_scheduler.remove_job = MagicMock()
    fake_scheduler.add_job = MagicMock()
    pitr_scheduler._scheduler = fake_scheduler

    with patch(
        "agflow.services.pitr_scheduler.pitr_config_service.get_config",
        new=AsyncMock(return_value=_make_fake_config(enabled=False)),
    ):
        await pitr_scheduler.reload_basebackup_schedule()

    fake_scheduler.remove_job.assert_called_with(pitr_scheduler.JOB_BASEBACKUP)
    # No add_job call since disabled
    job_ids = [c.kwargs.get("id") for c in fake_scheduler.add_job.call_args_list]
    assert pitr_scheduler.JOB_BASEBACKUP not in job_ids

    pitr_scheduler._scheduler = None


async def test_reload_basebackup_schedule_noop_if_scheduler_not_started():
    pitr_scheduler._scheduler = None
    # Should not raise
    await pitr_scheduler.reload_basebackup_schedule()


async def test_stop_idempotent():
    pitr_scheduler._scheduler = None
    await pitr_scheduler.stop()  # no-op, no exception
