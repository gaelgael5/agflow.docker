"""Tests du git_sync_scheduler (APScheduler wrapper)."""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from agflow.services import git_sync_scheduler

pytestmark = pytest.mark.asyncio


def _fake_config(*, cron_expr=None, cron_enabled=False):
    from agflow.schemas.git_sync import GitSyncConfigDTO
    return GitSyncConfigDTO(
        repo_url="url", auth_mode="pat_https", auth_secret_ref="ref",
        branch="main", commit_author_name="b", commit_author_email="b@l",
        excluded_columns={}, selected_tables=["t"],
        cron_expr=cron_expr, cron_enabled=cron_enabled,
        last_export_at=None, last_export_status=None, last_export_sha=None,
        last_export_error=None, last_export_tables_count=None,
        last_import_at=None, last_import_status=None, last_import_error=None,
        last_import_rows_inserted=None, last_import_rows_updated=None,
        last_import_rows_deleted=None,
        created_at=datetime(2026, 5, 17), updated_at=datetime(2026, 5, 17),
    )


async def test_start_then_stop_lifecycle():
    await git_sync_scheduler.start()
    assert git_sync_scheduler._scheduler is not None
    assert git_sync_scheduler._scheduler.running is True
    await git_sync_scheduler.stop()
    assert git_sync_scheduler._scheduler is None


async def test_reload_adds_export_job_when_cron_enabled():
    await git_sync_scheduler.start()
    try:
        with patch.object(git_sync_scheduler, "get_config",
                           AsyncMock(return_value=_fake_config(
                               cron_expr="0 4 * * *", cron_enabled=True))):
            await git_sync_scheduler.reload_schedule()
        assert git_sync_scheduler._scheduler.get_job("export") is not None
    finally:
        await git_sync_scheduler.stop()


async def test_reload_removes_export_job_when_disabled():
    await git_sync_scheduler.start()
    try:
        with patch.object(git_sync_scheduler, "get_config",
                           AsyncMock(return_value=_fake_config(
                               cron_expr="0 4 * * *", cron_enabled=True))):
            await git_sync_scheduler.reload_schedule()
        assert git_sync_scheduler._scheduler.get_job("export") is not None

        with patch.object(git_sync_scheduler, "get_config",
                           AsyncMock(return_value=_fake_config(
                               cron_expr="0 4 * * *", cron_enabled=False))):
            await git_sync_scheduler.reload_schedule()
        assert git_sync_scheduler._scheduler.get_job("export") is None
    finally:
        await git_sync_scheduler.stop()


async def test_reload_removes_job_when_no_config():
    await git_sync_scheduler.start()
    try:
        with patch.object(git_sync_scheduler, "get_config",
                           AsyncMock(return_value=_fake_config(
                               cron_expr="0 4 * * *", cron_enabled=True))):
            await git_sync_scheduler.reload_schedule()
        assert git_sync_scheduler._scheduler.get_job("export") is not None

        with patch.object(git_sync_scheduler, "get_config", AsyncMock(return_value=None)):
            await git_sync_scheduler.reload_schedule()
        assert git_sync_scheduler._scheduler.get_job("export") is None
    finally:
        await git_sync_scheduler.stop()


async def test_trigger_now_adds_date_trigger_job():
    await git_sync_scheduler.start()
    try:
        with patch.object(git_sync_scheduler, "run_export", AsyncMock()):
            await git_sync_scheduler.trigger_now()
        jobs = git_sync_scheduler._scheduler.get_jobs()
        assert any(j.id.startswith("trigger-now:") for j in jobs)
    finally:
        await git_sync_scheduler.stop()
