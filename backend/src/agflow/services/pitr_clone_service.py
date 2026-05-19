"""Lifecycle helpers for the active PITR clone."""
from __future__ import annotations

from datetime import UTC, datetime

import aiodocker
import structlog

from agflow.db.pool import execute, fetch_all, fetch_one
from agflow.schemas.pitr import CloneStatus

log = structlog.get_logger(__name__)

# Indirection for testability — tests patch _aiodocker, not aiodocker.Docker
_aiodocker = aiodocker.Docker

EXTEND_HOURS = 24


class NoActiveCloneError(LookupError):
    """No clone in status restoring/ready/terminating."""


async def get_active_clone() -> CloneStatus | None:
    row = await fetch_one(
        """
        SELECT c.*, b.pgbackrest_label
        FROM pitr_clones c
        JOIN pitr_basebackups b ON b.id = c.basebackup_id
        WHERE c.status IN ('restoring', 'ready', 'terminating')
        LIMIT 1
        """
    )
    if row is None:
        return None
    return _row_to_clone_status(row)


async def extend_active_clone() -> CloneStatus:
    active = await get_active_clone()
    if active is None:
        raise NoActiveCloneError("no active clone to extend")
    await execute(
        "UPDATE pitr_clones SET expires_at = expires_at + (INTERVAL '1 hour' * $2) "
        "WHERE id = $1",
        active.id, EXTEND_HOURS,
    )
    log.info("pitr.clone.extended", clone_id=str(active.id), hours=EXTEND_HOURS)
    refreshed = await get_active_clone()
    if refreshed is None:
        # Race: between the SELECT and the UPDATE, the clone was terminated by cleanup.
        # Treat as no-op.
        raise NoActiveCloneError("clone disappeared during extend")
    return refreshed


async def terminate_active_clone() -> None:
    row = await fetch_one(
        """
        SELECT id, postgres_container_name, pgweb_container_name
        FROM pitr_clones
        WHERE status IN ('restoring', 'ready', 'terminating')
        LIMIT 1
        """
    )
    if row is None:
        raise NoActiveCloneError("no active clone to terminate")

    await execute(
        "UPDATE pitr_clones SET status = 'terminating' WHERE id = $1", row["id"]
    )

    docker = _aiodocker()
    try:
        await _cleanup_artifacts(
            docker,
            postgres_name=row["postgres_container_name"],
            pgweb_name=row["pgweb_container_name"],
        )
        await execute(
            "UPDATE pitr_clones SET status='terminated', terminated_at=now() WHERE id = $1",
            row["id"],
        )
        log.info("pitr.clone.terminated", clone_id=str(row["id"]))
    finally:
        await docker.close()


async def cleanup_expired_clones() -> int:
    """Terminate any clones (restoring/ready) whose expires_at < now. Returns count."""
    expired = await fetch_all(
        "SELECT id FROM pitr_clones WHERE status IN ('restoring', 'ready') "
        "AND expires_at < now()"
    )
    if not expired:
        return 0
    count = 0
    for _row in expired:
        try:
            await terminate_active_clone()
            count += 1
        except NoActiveCloneError:
            # Already terminated between fetch and terminate — fine
            break
        except Exception as exc:
            log.error("pitr.clone.cleanup_error", error=str(exc))
    return count


# --- Private ---


async def _cleanup_artifacts(
    docker: object,
    *,
    postgres_name: str | None,
    pgweb_name: str | None,
) -> None:
    """Best-effort: stop+remove the 2 containers, drop the volume + network."""
    for cname in (pgweb_name, postgres_name):
        if not cname:
            continue
        try:
            c = await docker.containers.get(cname)  # type: ignore[attr-defined]
            await c.stop(timeout=10)
            await c.delete(force=True)
        except aiodocker.exceptions.DockerError:
            pass

    if postgres_name and postgres_name.startswith("agflow-pitr-clone-"):
        short = postgres_name[len("agflow-pitr-clone-"):]
        volume_name = f"agflow-pitr-clone-data-{short}"
        network_name = f"pitr-clone-net-{short}"
        try:
            vol = await docker.volumes.get(volume_name)  # type: ignore[attr-defined]
            await vol.delete()
        except aiodocker.exceptions.DockerError:
            pass
        try:
            net = await docker.networks.get(network_name)  # type: ignore[attr-defined]
            await net.delete()
        except aiodocker.exceptions.DockerError:
            pass


def _row_to_clone_status(row: dict) -> CloneStatus:  # type: ignore[type-arg]
    expires_at = row["expires_at"]
    expires_in_s = int((expires_at - datetime.now(UTC)).total_seconds())
    pgweb_url = None
    if row.get("pgweb_port"):
        pgweb_url = f"http://192.168.10.158:{row['pgweb_port']}"
    return CloneStatus(
        id=row["id"],
        basebackup_id=row["basebackup_id"],
        basebackup_label=row["pgbackrest_label"],
        target_time=row["target_time"],
        status=row["status"],
        error=row["error"],
        pgweb_url=pgweb_url,
        started_at=row["started_at"],
        ready_at=row["ready_at"],
        expires_at=expires_at,
        expires_in_seconds=expires_in_s,
    )
