from __future__ import annotations

import asyncio
from datetime import timedelta

import structlog

from agflow.db.pool import get_pool
from agflow.mom.consumer import MomConsumer
from agflow.services import platform_config_service

_log = structlog.get_logger(__name__)

_DEFAULT_INTERVAL_S = 15
_DEFAULT_STALE_THRESHOLD_S = 30

_RECLAIMED_GROUPS = ("dispatcher", "router", "ws_push")


async def reclaim_once() -> dict[str, int]:
    """Un tour de reclaim : reclaim_stale sur chaque groupe MOM.

    Retourne {group_name: count}.
    """
    threshold_s = await platform_config_service.get_int(
        "supervision_reclaim_stale_threshold_s",
        default=_DEFAULT_STALE_THRESHOLD_S,
    )
    max_idle = timedelta(seconds=threshold_s)
    pool = await get_pool()

    result: dict[str, int] = {}
    for group in _RECLAIMED_GROUPS:
        consumer = MomConsumer(
            pool=pool,
            group_name=group,
            consumer_id=f"reclaimer-{group}",
        )
        try:
            count = await consumer.reclaim_stale(max_idle=max_idle)
        except Exception as exc:
            _log.warning("mom_reclaimer.group_error", group=group, error=str(exc))
            count = 0
        result[group] = count
    return result


async def run_mom_reclaimer_loop(stop_event: asyncio.Event) -> None:
    interval_s = await platform_config_service.get_int(
        "supervision_reclaim_interval_s",
        default=_DEFAULT_INTERVAL_S,
    )
    _log.info("mom_reclaimer.started", interval_s=interval_s)
    try:
        while not stop_event.is_set():
            try:
                counts = await reclaim_once()
                total = sum(counts.values())
                if total:
                    _log.info("mom_reclaimer.reclaimed", **counts)
            except Exception as exc:
                _log.warning("mom_reclaimer.error", error=str(exc))
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_s)
            except TimeoutError:
                continue
    finally:
        _log.info("mom_reclaimer.stopped")
