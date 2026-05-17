"""AsyncIOScheduler dédié pour Git Sync (séparé de backup_scheduler).

Jobs gérés :
  - "export"        : cron user-defined (config.cron_expr) si cron_enabled
  - "__resync__"    : tick interne 30s qui appelle reload_schedule()
  - "trigger-now:*" : jobs DateTrigger(now) pour les bouton "Run now"
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from agflow.services import git_sync_service as svc
from agflow.services.git_sync_runner import run_export

_log = structlog.get_logger(__name__)

_RESYNC_INTERVAL_SECONDS = 30
_scheduler: AsyncIOScheduler | None = None


async def get_config():
    """Indirection pour faciliter le mock dans les tests."""
    return await svc.get_config()


async def start() -> None:
    """Démarre le scheduler et installe le tick __resync__."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        _resync_tick,
        IntervalTrigger(seconds=_RESYNC_INTERVAL_SECONDS),
        id="__resync__",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    _scheduler.start()
    await _resync_tick()
    _log.info("git_sync.scheduler.started")


async def stop() -> None:
    """Arrête proprement le scheduler."""
    global _scheduler
    if _scheduler is None:
        return
    _scheduler.shutdown(wait=True)
    _scheduler = None
    _log.info("git_sync.scheduler.stopped")


async def reload_schedule() -> None:
    """Relit la config et synchronise le job 'export'."""
    if _scheduler is None:
        return
    config = await get_config()
    existing = _scheduler.get_job("export")

    if config is None or not config.cron_enabled or not config.cron_expr:
        if existing is not None:
            _scheduler.remove_job("export")
            _log.info("git_sync.scheduler.export_job_removed")
        return

    try:
        trigger = CronTrigger.from_crontab(config.cron_expr)
    except ValueError:
        _log.warning("git_sync.scheduler.invalid_cron", cron_expr=config.cron_expr)
        if existing is not None:
            _scheduler.remove_job("export")
        return

    _scheduler.add_job(
        _safe_run_export,
        trigger,
        id="export",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    _log.info("git_sync.scheduler.export_job_set", cron_expr=config.cron_expr)


async def trigger_now() -> None:
    """Déclenche un export immédiat (job DateTrigger one-shot)."""
    if _scheduler is None:
        raise RuntimeError("scheduler not started")
    job_id = f"trigger-now:{uuid.uuid4()}"
    _scheduler.add_job(
        _safe_run_export,
        DateTrigger(run_date=datetime.now() + timedelta(seconds=1)),
        id=job_id,
        max_instances=1,
        coalesce=True,
    )
    _log.info("git_sync.scheduler.trigger_now", job_id=job_id)


async def _resync_tick() -> None:
    """Appelé toutes les _RESYNC_INTERVAL_SECONDS — relit la config."""
    try:
        await reload_schedule()
    except Exception as exc:
        _log.warning("git_sync.scheduler.resync_failed", error=str(exc))


async def _safe_run_export() -> None:
    """Wrapper qui catch tout (sinon APScheduler stoppe le job)."""
    try:
        await run_export()
    except Exception as exc:
        _log.warning("git_sync.scheduler.export_job_failed", error=str(exc))
