from __future__ import annotations

import asyncio

import structlog

from agflow.db.pool import fetch_one, get_pool
from agflow.services import (
    local_backups_service,
    system_anomaly_service,
)
from agflow.services import (
    remote_backup_connections_service as rbc_service,
)
from agflow.services.remote_backup_providers.factory import get_provider

_log = structlog.get_logger(__name__)
POLL_INTERVAL_S = 300  # toutes les 5 minutes


async def _has_new_data_since_last_backup() -> bool:
    """Retourne True si des données ont changé depuis le dernier backup (skip-if-no-change)."""
    row = await fetch_one(
        """
        SELECT
            (SELECT MAX(updated_at) FROM users) AS users_max,
            (SELECT MAX(created_at) FROM local_backups WHERE status = 'completed') AS last_backup
        """
    )
    if row is None or row["last_backup"] is None:
        return True  # pas encore de backup → toujours créer
    return (row["users_max"] or row["last_backup"]) > row["last_backup"]


async def _run_scheduled_push() -> None:
    """Crée un backup local et le pousse vers toutes les connexions configurées pour les snapshots."""
    async with (await get_pool()).acquire() as conn:
        connections = await rbc_service.list_connections(conn)

    snapshot_connections = [
        c
        for c in connections
        if c.has_credentials and rbc_service.resolve_remote_path(c.config, c.kind, "snapshots")
    ]

    if not snapshot_connections:
        return

    # skip si aucune donnée n'a changé depuis le dernier backup
    if not await _has_new_data_since_last_backup():
        _log.debug("remote_backup_pusher.skip_no_change")
        return

    # backup_lock est géré en interne par create_backup() — pas de ré-acquisition ici
    try:
        backup = await local_backups_service.create_backup()
    except Exception as exc:
        _log.error("remote_backup_pusher.backup_failed", error=str(exc))
        return

    for connection in snapshot_connections:
        remote_path = rbc_service.resolve_remote_path(connection.config, connection.kind, "snapshots")
        credentials = await rbc_service.fetch_credentials(connection)
        if credentials is None:
            continue
        try:
            provider = get_provider(connection.kind, connection.config, credentials)
            source = local_backups_service.stream_backup_chunks(backup.id)
            await provider.upload_stream(remote_path, backup.filename, source)
            _log.info(
                "remote_backup_pusher.push_ok",
                connection=connection.name,
                backup=backup.filename,
            )
        except Exception as exc:
            _log.error(
                "remote_backup_pusher.push_failed",
                connection=connection.name,
                error=str(exc),
            )
            await system_anomaly_service.create_anomaly(
                severity="critical",
                anomaly_type="remote_push_failed",
                source="snapshot_remote_push",
                source_ref_id=connection.id,
                message=f"Push vers {connection.name!r} échoué : {exc}",
                metadata={"filename": backup.filename, "error": str(exc)},
            )


async def run_remote_backup_pusher_loop(stop_event: asyncio.Event) -> None:
    _log.info("remote_backup_pusher.started", interval_s=POLL_INTERVAL_S)
    try:
        while not stop_event.is_set():
            try:
                await _run_scheduled_push()
            except Exception as exc:
                _log.warning("remote_backup_pusher.tick_error", error=str(exc))
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=POLL_INTERVAL_S)
            except TimeoutError:
                continue
    finally:
        _log.info("remote_backup_pusher.stopped")
