"""Job runner pour les schedules backups (full).

Appelé par APScheduler (cf. backup_scheduler.py). Orchestre :
1. Read schedule depuis DB, skip si enabled=false
2. local_backups_service.create_backup(source_schedule_full_id=...)
3. Si remote_connection_id : fetch_credentials + provider.upload_stream
4. record_run avec status final (ok/failed) + error éventuelle
5. prune_old_backups au-delà de retention_count
"""
from __future__ import annotations

from uuid import UUID

import structlog

from agflow.services import (
    backup_schedules_service as schedules_svc,
)
from agflow.services import (
    local_backups_service,
)
from agflow.services import remote_backup_connections_service as rbc_service
from agflow.services.remote_backup_providers.factory import get_provider

_log = structlog.get_logger(__name__)


async def run_full_job(schedule_id: UUID) -> None:
    """Exécute un schedule full : dump + push optionnel + record + prune."""
    try:
        schedule = await schedules_svc.get_full_schedule(schedule_id)
    except schedules_svc.ScheduleNotFoundError:
        _log.warning("backup_job_runner.full.schedule_not_found", id=str(schedule_id))
        return
    await _run_job(schedule=schedule, remote_kind_label="full")


async def _run_job(*, schedule, remote_kind_label: str) -> None:
    """Logique d'exécution d'un schedule full.

    `remote_kind_label` est passé à resolve_remote_path (convention 'full').
    """
    schedule_id = schedule.id

    if not schedule.enabled:
        _log.debug("backup_job_runner.full.skipped_disabled", id=str(schedule_id))
        return

    error: str | None = None
    status: str = "ok"
    backup = None
    try:
        # 1. Dump local
        backup = await local_backups_service.create_backup(
            source_schedule_full_id=schedule_id,
        )

        # 2. Push remote optionnel
        if schedule.remote_connection_id is not None:
            await _push_to_remote(
                connection_id=schedule.remote_connection_id,
                backup_id=backup.id,
                filename=backup.filename,
                remote_kind_label=remote_kind_label,
            )
    except Exception as exc:
        status = "failed"
        error = f"{type(exc).__name__}: {exc}"
        _log.error(
            "backup_job_runner.full.failed",
            schedule_id=str(schedule_id), error=error,
        )

    # 3. Record run (toujours, même en échec)
    await schedules_svc.record_run(
        schedule_id=schedule_id, kind="full", status=status, error=error,
    )

    # 4. Prune (uniquement si le backup local a été créé, pour préserver l'historique)
    if backup is not None:
        try:
            await schedules_svc.prune_old_backups(
                schedule_id=schedule_id, kind="full",
                retention_count=schedule.retention_count,
            )
        except Exception as exc:
            _log.warning(
                "backup_job_runner.full.prune_failed",
                schedule_id=str(schedule_id), error=str(exc),
            )


async def _push_to_remote(
    *,
    connection_id: UUID,
    backup_id: UUID,
    filename: str,
    remote_kind_label: str,
) -> None:
    """Push un backup local vers une remote_backup_connection. Lève si KO."""
    connection = await rbc_service.get_connection(None, connection_id)
    if connection is None:
        raise RuntimeError(f"Remote connection {connection_id} not found")

    credentials = await rbc_service.fetch_credentials(connection)
    if credentials is None:
        raise RuntimeError(f"No credentials for connection {connection_id}")

    remote_path = rbc_service.resolve_remote_path(
        connection.config, connection.kind, remote_kind_label,
    )
    provider = get_provider(connection.kind, connection.config, credentials)
    source = await local_backups_service.stream_backup_chunks(backup_id)
    await provider.upload_stream(remote_path, filename, source)
    _log.info(
        "backup_job_runner.pushed",
        connection=connection.name, filename=filename, kind=remote_kind_label,
    )
