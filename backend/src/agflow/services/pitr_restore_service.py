"""PITR restore — start_clone (public) + _provision_clone (background Docker provisioning)."""
from __future__ import annotations

import asyncio
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID

import aiodocker
import structlog

from agflow.db.pool import execute, fetch_one
from agflow.schemas.pitr import RestoreWindow

log = structlog.get_logger(__name__)

# Indirection for testability — patch `_aiodocker` in tests, NOT `aiodocker.Docker`
_aiodocker = aiodocker.Docker

CLONE_IMAGE = "agflow-postgres:16-pitr"
PGWEB_IMAGE = "sosedoff/pgweb:latest"
HEALTHCHECK_TIMEOUT_S = 300  # 5 min for postgres to become ready

CLONE_TTL_HOURS = 24


class RestoreWindowEmptyError(LookupError):
    """No OK basebackups with a populated recovery window."""


class InvalidTargetTimeError(ValueError):
    """target_time is outside the available restore window."""


class CloneAlreadyActiveError(RuntimeError):
    """A clone is already in status restoring/ready/terminating."""


async def get_restore_window() -> RestoreWindow:
    row = await fetch_one(
        "SELECT min(recovery_window_start) AS earliest, "
        "       max(recovery_window_end) AS latest "
        "FROM pitr_basebackups "
        "WHERE status = 'ok' "
        "  AND recovery_window_start IS NOT NULL "
        "  AND recovery_window_end IS NOT NULL"
    )
    if row is None or row["earliest"] is None or row["latest"] is None:
        raise RestoreWindowEmptyError("no basebackup with a valid recovery window")
    return RestoreWindow(earliest=row["earliest"], latest=row["latest"])


async def start_clone(target_time: datetime, *, actor_user_id: UUID | None) -> UUID:
    """Validate target_time, pick a basebackup, INSERT a 'restoring' clone row.

    Background `_provision_clone` is dispatched and the clone UUID is returned
    immediately so the API responds 202 Accepted without blocking.
    """
    win = await get_restore_window()
    if target_time < win.earliest or target_time > win.latest:
        raise InvalidTargetTimeError(
            f"target_time {target_time.isoformat()} is out of restore window "
            f"[{win.earliest.isoformat()}, {win.latest.isoformat()}]"
        )

    active = await fetch_one(
        "SELECT id FROM pitr_clones "
        "WHERE status IN ('restoring', 'ready', 'terminating') LIMIT 1"
    )
    if active:
        raise CloneAlreadyActiveError(str(active["id"]))

    basebackup = await fetch_one(
        "SELECT id, pgbackrest_label FROM pitr_basebackups "
        "WHERE status = 'ok' AND recovery_window_end >= $1 "
        "ORDER BY started_at ASC LIMIT 1",
        target_time,
    )
    if basebackup is None:
        raise InvalidTargetTimeError(
            f"no basebackup covers target_time {target_time.isoformat()}"
        )

    expires_at = datetime.now(UTC) + timedelta(hours=CLONE_TTL_HOURS)
    row = await fetch_one(
        "INSERT INTO pitr_clones (basebackup_id, target_time, status, expires_at, "
        "created_by_user_id) "
        "VALUES ($1, $2, 'restoring', $3, $4) RETURNING id",
        basebackup["id"], target_time, expires_at, actor_user_id,
    )
    if row is None:
        raise RuntimeError("INSERT pitr_clones returned no row")
    clone_id: UUID = row["id"]

    log.info(
        "pitr.clone.requested",
        clone_id=str(clone_id),
        basebackup_id=str(basebackup["id"]),
        target_time=target_time.isoformat(),
        actor_user_id=str(actor_user_id) if actor_user_id else None,
    )

    # RUF006: keep ref so task isn't GC'd before completion; errors handled inside
    _task = asyncio.create_task(_provision_clone(clone_id))
    del _task  # fire-and-forget
    return clone_id


async def _provision_clone(clone_id: UUID) -> None:
    """Create network + volume + postgres + pgweb containers for an active clone.

    Background task. On any failure marks the row 'failed' and cleans up artefacts.
    """
    short = secrets.token_hex(4)  # 8 hex chars
    clone_pg_name = f"agflow-pitr-clone-{short}"
    clone_pgweb_name = f"agflow-pitr-pgweb-{short}"
    network_name = f"pitr-clone-net-{short}"
    volume_name = f"agflow-pitr-clone-data-{short}"

    clone_row = await fetch_one(
        "SELECT target_time FROM pitr_clones WHERE id = $1", clone_id
    )
    if clone_row is None:
        log.error("pitr.clone.provision_no_row", clone_id=str(clone_id))
        return

    # pgBackRest expects target time in format "YYYY-MM-DD HH:MM:SS+00"
    target_str = clone_row["target_time"].strftime("%Y-%m-%d %H:%M:%S+00")

    docker = _aiodocker()
    try:
        # 1. Network
        await docker.networks.create({"Name": network_name, "Driver": "bridge"})
        log.info("pitr.clone.network_created", clone_id=str(clone_id), name=network_name)

        # 2. Volume
        await docker.volumes.create({"Name": volume_name})
        log.info("pitr.clone.volume_created", clone_id=str(clone_id), name=volume_name)

        # 3. Postgres clone container — restore mode
        pg_config = {
            "Image": CLONE_IMAGE,
            "Env": [
                "AGFLOW_PITR_MODE=restore",
                f"AGFLOW_PITR_TARGET_TIME={target_str}",
                "POSTGRES_PASSWORD=agflow",
                "POSTGRES_USER=agflow",
                "POSTGRES_DB=agflow",
            ],
            "HostConfig": {
                "NetworkMode": network_name,
                "Mounts": [
                    {
                        "Type": "volume",
                        "Source": volume_name,
                        "Target": "/var/lib/postgresql/data",
                    },
                    {
                        "Type": "volume",
                        "Source": "pgbackrest_repo",
                        "Target": "/var/lib/pgbackrest",
                        "ReadOnly": True,
                    },
                ],
                "AutoRemove": False,
            },
        }
        pg_container = await docker.containers.create_or_replace(
            name=clone_pg_name, config=pg_config
        )
        await pg_container.start()
        log.info(
            "pitr.clone.pg_container_started",
            clone_id=str(clone_id),
            container_id=pg_container.id,
        )

        # 4. Wait for postgres ready (pg_isready)
        if not await _wait_pg_ready(pg_container, timeout_s=HEALTHCHECK_TIMEOUT_S):
            raise RuntimeError(
                f"postgres clone {clone_pg_name} did not become ready within "
                f"{HEALTHCHECK_TIMEOUT_S}s"
            )

        # 5. pgweb container
        pgweb_config = {
            "Image": PGWEB_IMAGE,
            "Env": [
                f"DATABASE_URL=postgres://agflow:agflow@{clone_pg_name}:5432/agflow?sslmode=disable"
            ],
            "HostConfig": {
                "NetworkMode": network_name,
                "PortBindings": {"8081/tcp": [{"HostPort": ""}]},  # Docker picks a free port
                "AutoRemove": False,
            },
        }
        pgweb_container = await docker.containers.create_or_replace(
            name=clone_pgweb_name, config=pgweb_config
        )
        await pgweb_container.start()
        log.info(
            "pitr.clone.pgweb_container_started",
            clone_id=str(clone_id),
            container_id=pgweb_container.id,
        )

        # 6. Discover the host port assigned to pgweb's 8081
        info = await pgweb_container.show()
        port_bindings = (
            info.get("NetworkSettings", {}).get("Ports", {}).get("8081/tcp")
        )
        if not port_bindings or not port_bindings[0].get("HostPort"):
            raise RuntimeError(
                f"could not discover pgweb host port for {clone_pgweb_name}"
            )
        pgweb_port = int(port_bindings[0]["HostPort"])

        # 7. Mark ready
        await execute(
            "UPDATE pitr_clones SET status='ready', ready_at=now(), "
            "postgres_container_id=$2, postgres_container_name=$3, "
            "pgweb_container_id=$4, pgweb_container_name=$5, pgweb_port=$6 "
            "WHERE id = $1",
            clone_id,
            pg_container.id, clone_pg_name,
            pgweb_container.id, clone_pgweb_name, pgweb_port,
        )
        log.info("pitr.clone.ready", clone_id=str(clone_id), pgweb_port=pgweb_port)

    except Exception as exc:
        log.error("pitr.clone.provision_failed", clone_id=str(clone_id), error=str(exc))
        await execute(
            "UPDATE pitr_clones SET status='failed', error=$2 WHERE id = $1",
            clone_id, str(exc),
        )
        await _cleanup_clone_artifacts(
            docker, network_name, volume_name, clone_pg_name, clone_pgweb_name
        )
        # Don't re-raise — background task; API already returned 202
    finally:
        await docker.close()


async def _wait_pg_ready(
    container: object,
    *,
    timeout_s: int,
    interval_s: int = 2,
) -> bool:
    """Poll `pg_isready` inside the container until success or timeout."""
    elapsed = 0
    while elapsed < timeout_s:
        try:
            exec_obj = await container.exec(  # type: ignore[attr-defined]
                cmd=["pg_isready", "-U", "agflow"], stdout=True, stderr=True
            )
            async with exec_obj.start(detach=False) as stream:
                while True:
                    msg = await stream.read_out()
                    if msg is None:
                        break
            info = await exec_obj.inspect()
            if info.get("ExitCode") == 0:
                return True
        except aiodocker.exceptions.DockerError as exc:
            log.warning("pitr.clone.healthcheck_err", error=str(exc))
        await asyncio.sleep(interval_s)
        elapsed += interval_s
    return False


async def _cleanup_clone_artifacts(
    docker: object,
    network_name: str,
    volume_name: str,
    pg_name: str,
    pgweb_name: str,
) -> None:
    """Best-effort cleanup of any clone artefacts. Each step is independent."""
    for cname in (pgweb_name, pg_name):
        try:
            c = await docker.containers.get(cname)  # type: ignore[attr-defined]
            await c.stop(timeout=10)
            await c.delete(force=True)
        except aiodocker.exceptions.DockerError:
            pass  # already gone or never existed
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
