"""PITR scheduler — APScheduler worker for daily basebackup + clone cleanup + WAL refresh."""
from __future__ import annotations

import contextlib

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from agflow.services import (
    pitr_basebackup_service,
    pitr_clone_service,
    pitr_config_service,
    pitr_wal_archive_service,
)

log = structlog.get_logger(__name__)

_scheduler: AsyncIOScheduler | None = None

JOB_BASEBACKUP = "pitr_daily_basebackup"
JOB_CLEANUP = "pitr_clone_cleanup"
JOB_WAL_REFRESH = "pitr_wal_refresh"


async def start() -> None:
    """Start the APScheduler with 3 jobs. Idempotent — no-op if already started."""
    global _scheduler
    if _scheduler is not None:
        log.info("pitr.scheduler.already_started")
        return
    _scheduler = AsyncIOScheduler()
    config = await pitr_config_service.get_config()
    if config.enabled:
        _scheduler.add_job(
            _run_daily_basebackup,
            CronTrigger.from_crontab(config.basebackup_cron),
            id=JOB_BASEBACKUP,
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
    _scheduler.add_job(
        _run_clone_cleanup,
        IntervalTrigger(hours=1),
        id=JOB_CLEANUP,
        max_instances=1,
        replace_existing=True,
    )
    _scheduler.add_job(
        _run_wal_refresh,
        IntervalTrigger(minutes=5),
        id=JOB_WAL_REFRESH,
        max_instances=1,
        replace_existing=True,
    )
    _scheduler.start()
    log.info(
        "pitr.scheduler.started",
        cron=config.basebackup_cron,
        enabled=config.enabled,
    )


async def stop() -> None:
    """Stop the scheduler. Idempotent."""
    global _scheduler
    if _scheduler is None:
        return
    _scheduler.shutdown(wait=False)
    _scheduler = None
    log.info("pitr.scheduler.stopped")


async def reload_basebackup_schedule() -> None:
    """Re-read pitr_config + replace the basebackup job with the new cron.

    Called from API PUT /api/admin/pitr/config when cron or enabled changes.
    """
    if _scheduler is None:
        log.warning("pitr.scheduler.reload_skipped_no_scheduler")
        return
    config = await pitr_config_service.get_config()
    with contextlib.suppress(Exception):  # apscheduler raises a generic exception when job is missing
        _scheduler.remove_job(JOB_BASEBACKUP)
    if config.enabled:
        _scheduler.add_job(
            _run_daily_basebackup,
            CronTrigger.from_crontab(config.basebackup_cron),
            id=JOB_BASEBACKUP,
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
        log.info("pitr.scheduler.basebackup_reloaded", cron=config.basebackup_cron)
    else:
        log.info("pitr.scheduler.basebackup_disabled")


# --- Job bodies (catch-and-log so they don't kill the scheduler) ---


async def _run_daily_basebackup() -> None:
    try:
        await pitr_basebackup_service.trigger_basebackup_now(actor_user_id=None)
    except Exception as exc:
        log.error("pitr.scheduler.basebackup_failed", error=str(exc))


async def _run_clone_cleanup() -> None:
    try:
        n = await pitr_clone_service.cleanup_expired_clones()
        if n:
            log.info("pitr.scheduler.cleanup_done", count=n)
    except Exception as exc:
        log.error("pitr.scheduler.cleanup_failed", error=str(exc))


async def _run_wal_refresh() -> None:
    try:
        await pitr_wal_archive_service.refresh_recovery_windows()
    except Exception as exc:
        log.error("pitr.scheduler.wal_refresh_failed", error=str(exc))
