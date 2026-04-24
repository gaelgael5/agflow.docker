from __future__ import annotations

import asyncio

import structlog

from agflow.db.pool import fetch_all
from agflow.services import platform_config_service

_log = structlog.get_logger(__name__)

_DEFAULT_INTERVAL_S = 20
_DEFAULT_SESSION_IDLE_TIMEOUT_S = 120


_CLOSE_SQL = """
UPDATE sessions s
SET status = 'closed', closed_at = now()
WHERE s.status = 'active'
  AND s.created_at < now() - make_interval(secs => $1)
  AND NOT EXISTS (
    SELECT 1 FROM agents_instances ai
    WHERE ai.session_id = s.id
      AND ai.destroyed_at IS NULL
      AND ai.last_activity_at > now() - make_interval(secs => $1)
  )
RETURNING s.id
"""


async def reap_once() -> int:
    """Ferme les sessions actives sans agent actif depuis `session_idle_timeout_s`.

    Renvoie le nombre de sessions fermées.
    """
    timeout_s = await platform_config_service.get_int(
        "session_idle_timeout_s",
        default=_DEFAULT_SESSION_IDLE_TIMEOUT_S,
    )
    rows = await fetch_all(_CLOSE_SQL, timeout_s)
    if rows:
        _log.info(
            "session_idle_reaper.closed",
            count=len(rows),
            ids=[str(r["id"]) for r in rows],
        )
    return len(rows)


async def run_session_idle_reaper_loop(stop_event: asyncio.Event) -> None:
    interval_s = await platform_config_service.get_int(
        "supervision_reaper_interval_s",
        default=_DEFAULT_INTERVAL_S,
    )
    _log.info("session_idle_reaper.started", interval_s=interval_s)
    try:
        while not stop_event.is_set():
            try:
                count = await reap_once()
                if count:
                    _log.info("session_idle_reaper.swept", count=count)
            except Exception as exc:
                _log.warning("session_idle_reaper.error", error=str(exc))
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_s)
            except TimeoutError:
                continue
    finally:
        _log.info("session_idle_reaper.stopped")
