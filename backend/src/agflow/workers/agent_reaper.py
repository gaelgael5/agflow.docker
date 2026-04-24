from __future__ import annotations

import asyncio

import structlog

from agflow.db.pool import fetch_all
from agflow.services import container_runner, platform_config_service

_log = structlog.get_logger(__name__)

_DEFAULT_INTERVAL_S = 20
_DEFAULT_AGENT_IDLE_TIMEOUT_S = 600


_REAP_SQL = """
UPDATE agents_instances
SET destroyed_at = now(), status = 'destroyed'
WHERE destroyed_at IS NULL
  AND status = 'idle'
  AND last_activity_at < now() - make_interval(secs => $1)
RETURNING id, session_id, agent_id, last_container_name
"""


async def reap_once() -> int:
    """Un tour de reaper : destroy les agents idle dépassés + stop containers.

    Renvoie le nombre d'instances détruites.
    """
    timeout_s = await platform_config_service.get_int(
        "agent_idle_timeout_s",
        default=_DEFAULT_AGENT_IDLE_TIMEOUT_S,
    )
    rows = await fetch_all(_REAP_SQL, timeout_s)
    if not rows:
        return 0

    for row in rows:
        instance_id = row["id"]
        container_name = row["last_container_name"]
        _log.info(
            "agent_reaper.destroyed",
            instance_id=str(instance_id),
            session_id=str(row["session_id"]),
            agent_id=row["agent_id"],
        )
        if container_name:
            try:
                await container_runner.stop(container_name)
            except container_runner.ContainerNotFoundError:
                # Container déjà absent : rien à faire.
                pass
            except Exception as exc:
                _log.warning(
                    "agent_reaper.stop_failed",
                    instance_id=str(instance_id),
                    container=container_name,
                    error=str(exc),
                )
    return len(rows)


async def run_agent_reaper_loop(stop_event: asyncio.Event) -> None:
    interval_s = await platform_config_service.get_int(
        "supervision_reaper_interval_s",
        default=_DEFAULT_INTERVAL_S,
    )
    _log.info("agent_reaper.started", interval_s=interval_s)
    try:
        while not stop_event.is_set():
            try:
                count = await reap_once()
                if count:
                    _log.info("agent_reaper.swept", count=count)
            except Exception as exc:
                _log.warning("agent_reaper.error", error=str(exc))
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_s)
            except TimeoutError:
                continue
    finally:
        _log.info("agent_reaper.stopped")
