"""Wrapper APScheduler pour les schedules backups.

Charge les schedules depuis DB au start, sync périodiquement (tick 30s).
Délègue l'exécution à backup_job_runner.run_full_job / run_snapshot_job.

Pattern d'id de job APScheduler : "full:<schedule_uuid>" / "snapshot:<schedule_uuid>".
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from agflow.services import backup_job_runner
from agflow.services import backup_schedules_service as schedules_svc

_log = structlog.get_logger(__name__)
_scheduler: AsyncIOScheduler | None = None

_RESYNC_INTERVAL_S = 30


async def start() -> None:
    """Démarre le scheduler + charge les jobs depuis DB + planifie re-sync 30s."""
    global _scheduler
    if _scheduler is not None:
        _log.warning("backup_scheduler.already_started")
        return
    _scheduler = AsyncIOScheduler()
    _scheduler.start()
    await reload_schedules()
    # Job de re-sync périodique : utilise un id stable pour ne pas dupliquer
    _scheduler.add_job(
        reload_schedules,
        IntervalTrigger(seconds=_RESYNC_INTERVAL_S),
        id="__resync__",
        replace_existing=True,
    )
    _log.info("backup_scheduler.started", resync_interval_s=_RESYNC_INTERVAL_S)


async def stop() -> None:
    """Arrête le scheduler proprement."""
    global _scheduler
    if _scheduler is None:
        return
    _scheduler.shutdown(wait=False)
    _scheduler = None
    _log.info("backup_scheduler.stopped")


async def reload_schedules() -> None:
    """Lit les schedules en DB, sync avec APScheduler (ADD/REMOVE).

    MVP : pas de MODIFY (on supprime + re-crée si updated_at change). Simple.
    """
    if _scheduler is None:
        _log.warning("backup_scheduler.reload_no_scheduler")
        return

    full_schedules = await schedules_svc.list_full_schedules()
    snapshot_schedules = await schedules_svc.list_snapshot_schedules()

    # IDs attendus côté APScheduler (uniquement les enabled)
    expected_ids = set()
    for s in full_schedules:
        if s.enabled:
            expected_ids.add(f"full:{s.id}")
    for s in snapshot_schedules:
        if s.enabled:
            expected_ids.add(f"snapshot:{s.id}")

    # IDs actuels dans APScheduler (hors le job de re-sync)
    current_ids = {
        j.id for j in _scheduler.get_jobs()
        if j.id != "__resync__" and not j.id.startswith("trigger-now:")
    }

    # Supprime les jobs orphelins (absents en DB ou disabled)
    for orphan_id in current_ids - expected_ids:
        _scheduler.remove_job(orphan_id)
        _log.info("backup_scheduler.job_removed", id=orphan_id)

    # Ajoute les nouveaux jobs (présents en DB mais absents dans APScheduler)
    for s in full_schedules:
        if not s.enabled:
            continue
        job_id = f"full:{s.id}"
        if job_id in current_ids:
            continue  # MVP : pas de MODIFY, juste ADD pour les nouveaux
        try:
            trigger = CronTrigger.from_crontab(s.cron_expr)
            _scheduler.add_job(
                backup_job_runner.run_full_job,
                trigger,
                args=[s.id],
                id=job_id,
                max_instances=1,
                coalesce=True,
                replace_existing=True,
            )
            _log.info("backup_scheduler.job_added", id=job_id, cron=s.cron_expr)
        except Exception as exc:
            _log.warning("backup_scheduler.job_add_failed", id=job_id, error=str(exc))

    for s in snapshot_schedules:
        if not s.enabled:
            continue
        job_id = f"snapshot:{s.id}"
        if job_id in current_ids:
            continue
        try:
            kwargs = {s.interval_unit: s.interval_amount}
            trigger = IntervalTrigger(**kwargs)
            _scheduler.add_job(
                backup_job_runner.run_snapshot_job,
                trigger,
                args=[s.id],
                id=job_id,
                max_instances=1,
                coalesce=True,
                replace_existing=True,
            )
            _log.info(
                "backup_scheduler.job_added",
                id=job_id,
                interval=f"{s.interval_amount} {s.interval_unit}",
            )
        except Exception as exc:
            _log.warning("backup_scheduler.job_add_failed", id=job_id, error=str(exc))


async def trigger_now(
    *, schedule_id: UUID, kind: Literal["full", "snapshot"],
) -> None:
    """Déclenche immédiatement un job, indépendant du schedule régulier."""
    if _scheduler is None:
        raise RuntimeError("backup_scheduler not started")

    runner = (
        backup_job_runner.run_full_job if kind == "full"
        else backup_job_runner.run_snapshot_job
    )
    eph_id = f"trigger-now:{kind}:{schedule_id}:{datetime.now(UTC).timestamp()}"
    _scheduler.add_job(
        runner,
        DateTrigger(run_date=datetime.now(UTC)),
        args=[schedule_id],
        id=eph_id,
        next_run_time=datetime.now(UTC),
    )
    _log.info(
        "backup_scheduler.trigger_now",
        schedule_id=str(schedule_id), kind=kind, ephemeral_id=eph_id,
    )
