from __future__ import annotations

import asyncio

import structlog

from agflow.services import sessions_service

_log = structlog.get_logger(__name__)

POLL_INTERVAL_S = 30


async def run_expiry_loop(stop_event: asyncio.Event) -> None:
    _log.info("session_expiry.started", interval_s=POLL_INTERVAL_S)
    try:
        while not stop_event.is_set():
            try:
                count = await sessions_service.expire_stale()
                if count:
                    _log.info("session_expiry.swept", count=count)
            except Exception as exc:
                _log.warning("session_expiry.error", error=str(exc))
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=POLL_INTERVAL_S)
            except TimeoutError:
                continue
    finally:
        _log.info("session_expiry.stopped")
