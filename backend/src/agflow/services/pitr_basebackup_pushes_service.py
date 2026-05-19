"""Push basebackups to remote storage + retention pruning.

Split from pitr_basebackup_service.py to keep both files under 300 lines
per CLAUDE.md.
"""
from __future__ import annotations

import json
from uuid import UUID

import structlog

from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.services.pitr_basebackup_service import (
    STANZA,
    BasebackupNotFoundError,
    _pg_exec,
)

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class PushNotFoundError(LookupError):
    """Raised when a (basebackup_id, remote_connection_id) push entry doesn't exist."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _pgbackrest_local_path(label: str) -> str:
    """Return the local path to a pgbackrest backup set by label."""
    return f"/var/lib/pgbackrest/backup/{STANZA}/{label}"


async def _provider_for(remote_id: UUID):
    """Resolve a remote_backup_connection to an instantiated provider."""
    from agflow.services.remote_backup_connections_service import _fetch_row_by_id
    from agflow.services.remote_backup_providers.factory import get_provider

    row = await _fetch_row_by_id(remote_id)
    if row is None:
        raise LookupError(f"remote_backup_connection {remote_id} not found")

    config = row["config"] if isinstance(row["config"], dict) else json.loads(row["config"])
    # Credentials are stored in Harpocrate; for PITR pushes we pass an empty
    # dict when vault_secret_path is absent (unauthenticated remotes, tests).
    # Callers that require credentials must ensure they are populated in vault.
    credentials: dict = {}
    if row.get("vault_secret_path"):
        from agflow.services import vault_client

        raw = await vault_client.get_secret(row["vault_secret_path"])
        credentials = json.loads(raw)

    return get_provider(row["kind"], config, credentials)


# ---------------------------------------------------------------------------
# Push
# ---------------------------------------------------------------------------


async def push_basebackup(basebackup_id: UUID, remote_id: UUID) -> None:
    """Re-push a basebackup to a remote. Idempotent: status='ok' is a no-op.

    On success the push row is marked ok with remote_path and size_bytes.
    On provider failure the row is marked failed and the exception is re-raised.
    """
    push = await fetch_one(
        "SELECT id, status FROM pitr_basebackup_pushes "
        "WHERE basebackup_id = $1 AND remote_connection_id = $2",
        basebackup_id,
        remote_id,
    )
    if push is None:
        raise PushNotFoundError(f"{basebackup_id}/{remote_id}")
    if push["status"] == "ok":
        log.info(
            "pitr.push.skip_already_ok",
            basebackup_id=str(basebackup_id),
            remote_id=str(remote_id),
        )
        return

    bb = await fetch_one(
        "SELECT pgbackrest_label FROM pitr_basebackups WHERE id = $1",
        basebackup_id,
    )
    if bb is None:
        raise BasebackupNotFoundError(str(basebackup_id))

    await execute(
        "UPDATE pitr_basebackup_pushes SET status = 'pushing', error = NULL WHERE id = $1",
        push["id"],
    )

    try:
        provider = await _provider_for(remote_id)
        tarball_path = _pgbackrest_local_path(bb["pgbackrest_label"])
        # upload_stream(path, filename, source) → int (bytes written)
        # For PITR tarballs we stream from the local filesystem via an async
        # file iterator. The remote_path stored is path/filename.
        remote_dir = "pitr"
        filename = f"{bb['pgbackrest_label']}.tar.gz"

        async def _file_chunks():
            import aiofiles

            async with aiofiles.open(tarball_path, "rb") as fh:
                while chunk := await fh.read(65536):
                    yield chunk

        size_bytes: int = await provider.upload_stream(remote_dir, filename, _file_chunks())
        remote_path = f"{remote_dir}/{filename}"
        await execute(
            "UPDATE pitr_basebackup_pushes "
            "SET status = 'ok', pushed_at = now(), remote_path = $2, size_bytes = $3 "
            "WHERE id = $1",
            push["id"],
            remote_path,
            size_bytes,
        )
        log.info(
            "pitr.push.ok",
            basebackup_id=str(basebackup_id),
            remote_id=str(remote_id),
            remote_path=remote_path,
        )
    except Exception as exc:
        await execute(
            "UPDATE pitr_basebackup_pushes SET status = 'failed', error = $2 WHERE id = $1",
            push["id"],
            str(exc),
        )
        log.error(
            "pitr.push.failed",
            basebackup_id=str(basebackup_id),
            remote_id=str(remote_id),
            error=str(exc),
        )
        raise


# ---------------------------------------------------------------------------
# Orchestrate all pending pushes for a basebackup
# ---------------------------------------------------------------------------


async def _push_to_remotes(basebackup_id: UUID) -> None:
    """For each pending push of this basebackup, try to push.

    A failure on one remote does not interrupt the others — each error is
    logged and the push row is marked 'failed' by push_basebackup itself.
    """
    pending = await fetch_all(
        "SELECT remote_connection_id FROM pitr_basebackup_pushes "
        "WHERE basebackup_id = $1 AND status = 'pending'",
        basebackup_id,
    )
    for r in pending:
        try:
            await push_basebackup(basebackup_id, r["remote_connection_id"])
        except Exception as exc:
            log.error(
                "pitr.push.failed_iter",
                basebackup_id=str(basebackup_id),
                remote_id=str(r["remote_connection_id"]),
                error=str(exc),
            )


# ---------------------------------------------------------------------------
# Prune old basebackups
# ---------------------------------------------------------------------------


async def _prune_old_basebackups(retention_count: int) -> int:
    """Run pgbackrest expire then sync the DB with what pgbackrest kept.

    Returns the count of pitr_basebackups rows deleted from the DB.

    Defensive: if pgbackrest info returns an empty backup list (unexpected),
    the function returns 0 without touching the DB to avoid wiping everything.
    """
    if retention_count < 1:
        raise ValueError(f"retention_count must be >= 1, got {retention_count}")

    code, _, err = await _pg_exec(
        [
            "--stanza=" + STANZA,
            "expire",
            f"--repo1-retention-full={retention_count}",
        ]
    )
    if code != 0:
        raise RuntimeError(f"pgbackrest expire failed: {err}")

    code, out, _ = await _pg_exec(["--stanza=" + STANZA, "info", "--output=json"])
    if code != 0 or not out.strip():
        return 0

    info = json.loads(out)
    alive_labels: set[str] = (
        {b["label"] for b in info[0].get("backup", [])} if info else set()
    )

    # Defensive: don't wipe the table if pgbackrest info is unparseable / empty
    if not alive_labels:
        return 0

    # Delete dependent pushes first (RESTRICT FK), then the expired basebackups
    result = await fetch_one(
        """
        WITH expired AS (
            SELECT id FROM pitr_basebackups
            WHERE status = 'ok' AND pgbackrest_label <> ALL($1::text[])
        ),
        del_pushes AS (
            DELETE FROM pitr_basebackup_pushes WHERE basebackup_id IN (SELECT id FROM expired)
        ),
        del_basebackups AS (
            DELETE FROM pitr_basebackups WHERE id IN (SELECT id FROM expired) RETURNING id
        )
        SELECT count(*)::int AS n FROM del_basebackups
        """,
        list(alive_labels),
    )
    deleted = int(result["n"]) if result else 0
    if deleted:
        log.info("pitr.basebackup.pruned", count=deleted, retention_count=retention_count)
    return deleted
