"""Worker startup qui purge les pending OAuth expirés/consumed.

Tick configurable (défaut 5 min). Démarré dans `main.lifespan`.
"""
from __future__ import annotations

import asyncio

import structlog

from agflow.db.pool import fetch_one

_log = structlog.get_logger(__name__)

_DEFAULT_INTERVAL_S = 300  # 5 min


async def purge_oauth_pending() -> int:
    """Supprime les pending rows expirées (> 1h) OR consommées. Retourne le nb supprimé."""
    row = await fetch_one(
        """
        WITH deleted AS (
            DELETE FROM oauth_pending_session
            WHERE expires_at < now() - interval '1 hour'
               OR consumed_at IS NOT NULL
            RETURNING id
        )
        SELECT COUNT(*) AS n FROM deleted
        """,
    )
    n = int(row["n"]) if row else 0
    if n > 0:
        _log.info("oauth_pending.purged", count=n)
    return n


async def run_reaper_loop(
    stop_event: asyncio.Event,
    interval_s: int = _DEFAULT_INTERVAL_S,
) -> None:
    """Boucle infinie qui appelle purge à intervalle régulier."""
    _log.info("oauth_pending_reaper.started", interval_s=interval_s)
    try:
        while not stop_event.is_set():
            try:
                await purge_oauth_pending()
            except Exception as exc:
                _log.warning("oauth_pending_reaper.error", error=str(exc)[:200])
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_s)
            except TimeoutError:
                continue
    finally:
        _log.info("oauth_pending_reaper.stopped")
