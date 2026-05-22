"""Push history per remote pour les backups locaux."""
from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.schemas.local_backup_pushes import LocalBackupPushSummary

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class PushNotFoundError(LookupError):
    """Aucune entrée local_backup_pushes pour (backup, remote)."""


class LocalFileMissingError(RuntimeError):
    """Le fichier local est absent (local_file_present=false ou row backup absente)."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def seed_pushes(*, backup_id: UUID, remote_ids: list[UUID]) -> None:
    """INSERT 1 row 'pending' par remote. ON CONFLICT DO NOTHING (idempotent)."""
    for rid in remote_ids:
        await execute(
            "INSERT INTO local_backup_pushes (local_backup_id, remote_connection_id, status) "
            "VALUES ($1, $2, 'pending') "
            "ON CONFLICT (local_backup_id, remote_connection_id) DO NOTHING",
            backup_id,
            rid,
        )


async def list_pushes(backup_id: UUID) -> list[LocalBackupPushSummary]:
    """Retourne toutes les entrées de push pour un backup, avec le nom du remote."""
    rows = await fetch_all(
        """
        SELECT p.id, p.local_backup_id, p.remote_connection_id,
               r.name AS remote_connection_name,
               p.status, p.pushed_at, p.error, p.remote_path, p.size_bytes,
               p.created_at, p.updated_at
        FROM local_backup_pushes p
        JOIN remote_backup_connections r ON r.id = p.remote_connection_id
        WHERE p.local_backup_id = $1
        ORDER BY p.created_at ASC
        """,
        backup_id,
    )
    return [LocalBackupPushSummary(**r) for r in rows]


async def push_all_pending(*, backup_id: UUID) -> bool:
    """Tente de pusher toutes les entrées 'pending'/'failed' du backup.

    Les erreurs par-remote sont catchées et loggées ; la row est marquée
    'failed' par push_one lui-même.

    Retourne True si TOUS les pushes du backup sont 'ok' au final.
    """
    pending = await fetch_all(
        "SELECT remote_connection_id FROM local_backup_pushes "
        "WHERE local_backup_id = $1 AND status IN ('pending', 'failed')",
        backup_id,
    )
    for row in pending:
        try:
            await push_one(backup_id=backup_id, remote_id=row["remote_connection_id"])
        except Exception as exc:
            log.error(
                "local_backup_push.failed",
                backup_id=str(backup_id),
                remote_id=str(row["remote_connection_id"]),
                error=str(exc),
            )

    not_ok = await fetch_one(
        "SELECT count(*)::int AS n FROM local_backup_pushes "
        "WHERE local_backup_id = $1 AND status != 'ok'",
        backup_id,
    )
    return not_ok["n"] == 0


async def push_one(*, backup_id: UUID, remote_id: UUID) -> LocalBackupPushSummary:
    """Re-push manuel vers un remote précis.

    - Idempotent si status='ok' (no-op, retourne le résumé existant).
    - Lève PushNotFoundError si la row (backup, remote) n'existe pas.
    - Lève LocalFileMissingError si local_file_present=false ou backup introuvable.
    """
    push_row = await fetch_one(
        "SELECT id, status FROM local_backup_pushes "
        "WHERE local_backup_id = $1 AND remote_connection_id = $2",
        backup_id,
        remote_id,
    )
    if push_row is None:
        raise PushNotFoundError(f"{backup_id}/{remote_id}")

    if push_row["status"] == "ok":
        return next(
            p
            for p in (await list_pushes(backup_id))
            if p.remote_connection_id == remote_id
        )

    backup = await fetch_one(
        "SELECT file_path, filename, local_file_present FROM local_backups WHERE id = $1",
        backup_id,
    )
    if backup is None or not backup["local_file_present"]:
        raise LocalFileMissingError(str(backup_id))

    await execute(
        "UPDATE local_backup_pushes SET status='pushing', error=NULL WHERE id=$1",
        push_row["id"],
    )

    try:
        provider, remote_dir = await _provider_for(remote_id)
        remote_path, size_bytes = await _push_to_remote(
            provider=provider,
            local_file_path=backup["file_path"],
            filename=backup["filename"],
            remote_dir=remote_dir,
        )
        await execute(
            "UPDATE local_backup_pushes "
            "SET status='ok', pushed_at=now(), remote_path=$2, size_bytes=$3 "
            "WHERE id=$1",
            push_row["id"],
            remote_path,
            size_bytes,
        )
        log.info(
            "local_backup_push.ok",
            backup_id=str(backup_id),
            remote_id=str(remote_id),
            remote_path=remote_path,
        )
    except Exception as exc:
        await execute(
            "UPDATE local_backup_pushes SET status='failed', error=$2 WHERE id=$1",
            push_row["id"],
            str(exc),
        )
        raise

    return next(
        p
        for p in (await list_pushes(backup_id))
        if p.remote_connection_id == remote_id
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


async def _provider_for(remote_id: UUID) -> tuple:
    """Résout la connexion + credentials + instancie le provider.

    Retourne (provider, remote_dir) où remote_dir est le chemin configuré
    pour les full backups (remote_path_full), ou "full" si non configuré.
    """
    from agflow.services.remote_backup_connections_service import (
        _fetch_row_by_id,
        inject_certificate_credentials,
        resolve_remote_path,
    )
    from agflow.services.remote_backup_providers.factory import get_provider

    conn_row = await _fetch_row_by_id(remote_id)
    if conn_row is None:
        raise LookupError(f"remote_backup_connection not found: {remote_id}")

    config = (
        conn_row["config"]
        if isinstance(conn_row["config"], dict)
        else json.loads(conn_row["config"])
    )

    credentials: dict = {}
    if conn_row.get("vault_secret_path"):
        from agflow.services.remote_backup_connections_service import (
            _read_vault_credentials,
        )
        credentials = await _read_vault_credentials(conn_row["vault_secret_path"])

    credentials = await inject_certificate_credentials(config, credentials)
    provider = get_provider(conn_row["kind"], config, credentials)
    remote_dir = resolve_remote_path(config, conn_row["kind"], "full") or "full"
    return provider, remote_dir


async def _push_to_remote(
    *,
    provider,
    local_file_path: str,
    filename: str,
    remote_dir: str,
) -> tuple[str, int]:
    """Upload via provider.upload_stream. Retourne (remote_path, size_bytes)."""

    async def _file_chunks():
        path = Path(local_file_path)
        with path.open("rb") as fh:
            while chunk := fh.read(65536):
                yield chunk

    size_bytes: int = await provider.upload_stream(remote_dir, filename, _file_chunks())
    remote_path = f"{remote_dir}/{filename}"
    return remote_path, size_bytes
