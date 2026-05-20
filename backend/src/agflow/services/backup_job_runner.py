"""Job runner pour les schedules backups (full).

Appelé par APScheduler (cf. backup_scheduler.py). Orchestre :
1. Lit le schedule depuis DB — skip si disabled
2. local_backups_service.create_backup(source_schedule_full_id=...)
3. Si remote_connection_ids : seed_pushes 'pending' + push_all_pending
4. Si keep_local=false ET tous pushes ok : delete_file_only
5. record_run avec status final (ok/failed) + prune_old_backups
"""
from __future__ import annotations

from uuid import UUID

import structlog

from agflow.services import (
    backup_schedules_service,
    local_backup_pushes_service,
    local_backups_service,
)

log = structlog.get_logger(__name__)


async def run_full_job(schedule_id: UUID) -> None:
    """Cycle de vie d'un job 'full' :
    1. Lit le schedule (si disabled → no-op)
    2. Crée le local_backup (mandatory — source des pushes)
    3. Si remote_connection_ids : seed pushes 'pending' + push_all_pending
    4. Si keep_local=false ET tous pushes ok : delete_file_only
    5. record_run + prune_old_backups
    """
    try:
        schedule = await backup_schedules_service.get_full_schedule(schedule_id)
    except backup_schedules_service.ScheduleNotFoundError:
        log.warning("backup_job_runner.full.schedule_not_found", id=str(schedule_id))
        return

    if not schedule.enabled:
        log.info("backup_job.skip_disabled", schedule_id=str(schedule_id))
        return

    try:
        # 1) Création du backup local
        backup = await local_backups_service.create_backup(
            source_schedule_full_id=schedule_id,
        )

        # 2) Pushes (si la planif a des remotes)
        all_pushes_ok = True
        if schedule.remote_connection_ids:
            await local_backup_pushes_service.seed_pushes(
                backup_id=backup.id,
                remote_ids=schedule.remote_connection_ids,
            )
            all_pushes_ok = await local_backup_pushes_service.push_all_pending(
                backup_id=backup.id,
            )

        # 3) Suppression fichier si keep_local=false ET tous pushes ok
        if not schedule.keep_local and all_pushes_ok:
            await local_backups_service.delete_file_only(backup.id)

        # 4) Record run (toujours 'ok' si on arrive ici — les pushes partiellement échoués
        #    sont visibles via les badges sur le local_backup)
        await backup_schedules_service.record_run(
            schedule_id=schedule_id, kind="full", status="ok",
        )

        # 5) Prune
        await backup_schedules_service.prune_old_backups(
            schedule_id=schedule_id,
            kind="full",
            retention_count=schedule.retention_count,
        )

    except Exception as exc:
        log.error(
            "backup_job.failed",
            schedule_id=str(schedule_id),
            error=str(exc),
        )
        await backup_schedules_service.record_run(
            schedule_id=schedule_id, kind="full", status="failed", error=str(exc),
        )
        raise
