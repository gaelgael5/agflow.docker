from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import structlog

from agflow.db.pool import execute, fetch_all
from agflow.schemas.containers import ContainerInfo
from agflow.services import container_runner

_log = structlog.get_logger(__name__)


ListRunningFn = Callable[[], Awaitable[list[ContainerInfo]]]
StopFn = Callable[[str], Awaitable[None]]


async def run_docker_reconciliation(
    *,
    list_running_fn: ListRunningFn | None = None,
    stop_fn: StopFn | None = None,
) -> dict[str, Any]:
    """Synchronise l'état Docker avec la table agents_instances au démarrage.

    - Cas A : instance DB + container présent → no-op.
    - Cas B : instance DB `last_container_name` mais container disparu → status='error'.
    - Cas C : container running orphelin (pas d'instance DB non-destroyed) → stop.

    Retourne un résumé {orphans_stopped, missing_containers, ok}.
    """
    lrf = list_running_fn or container_runner.list_running
    sf = stop_fn or container_runner.stop

    try:
        containers = await lrf()
    except Exception as exc:
        _log.warning("docker_reconciler.list_failed", error=str(exc))
        return {"orphans_stopped": 0, "missing_containers": 0, "ok": False}

    by_instance: dict[str, ContainerInfo] = {}
    unlabeled: list[ContainerInfo] = []
    for c in containers:
        if c.instance_id:
            by_instance[c.instance_id] = c
        else:
            unlabeled.append(c)

    rows = await fetch_all(
        """
        SELECT id, last_container_name, status
        FROM agents_instances
        WHERE destroyed_at IS NULL AND last_container_name IS NOT NULL
        """,
    )

    missing = 0
    for row in rows:
        iid = str(row["id"])
        if iid in by_instance:
            continue
        # Container associé a disparu → on marque en error
        await execute(
            """
            UPDATE agents_instances
            SET status = 'error', error_message = 'container disappeared'
            WHERE id = $1 AND destroyed_at IS NULL AND status <> 'destroyed'
            """,
            row["id"],
        )
        missing += 1
        _log.warning(
            "docker_reconciler.instance_container_missing",
            instance_id=iid,
            container=row["last_container_name"],
        )

    # Cas C : containers orphelins (instance_id label non mappable à une instance DB active)
    known_instances = {str(r["id"]) for r in rows}
    orphans = 0
    for c in containers:
        if not c.instance_id:
            continue
        if c.instance_id in known_instances:
            continue
        try:
            await sf(c.id)
            orphans += 1
            _log.warning(
                "docker_reconciler.orphan_stopped",
                container=c.name,
                instance_label=c.instance_id,
            )
        except container_runner.ContainerNotFoundError:
            pass
        except Exception as exc:
            _log.warning(
                "docker_reconciler.orphan_stop_failed",
                container=c.name,
                error=str(exc),
            )

    summary = {
        "orphans_stopped": orphans,
        "missing_containers": missing,
        "ok": True,
    }
    _log.info("docker_reconciler.done", **summary)
    return summary
