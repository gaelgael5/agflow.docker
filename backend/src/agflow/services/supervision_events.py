"""Pub/sub des événements de supervision via PostgreSQL pg_notify.

Channel : `supervision_events`.
Payload : JSON event-rich (cf. spec 2026-05-17-m6-supervision-ws-push-design.md).

Les `publish_*` sont fire-and-forget : toute exception DB est loggée
mais NE propage PAS (la mutation métier reste atomique).
"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from uuid import UUID

import asyncpg
import structlog

from agflow.db.pool import get_pool

_log = structlog.get_logger(__name__)

CHANNEL = "supervision_events"


async def _safe_notify(payload: dict) -> None:
    try:
        pool = await get_pool()
        await pool.execute(
            "SELECT pg_notify($1, $2)",
            CHANNEL,
            json.dumps(payload, ensure_ascii=False),
        )
    except Exception as exc:
        _log.warning(
            "supervision_events.publish_failed",
            event_type=payload.get("type"),
            error=str(exc),
        )


async def publish_instance_created(
    *, instance_id: UUID, session_id: UUID
) -> None:
    await _safe_notify(
        {
            "type": "instance.created",
            "id": str(instance_id),
            "session_id": str(session_id),
        }
    )


async def publish_instance_status_changed(*, instance_id: UUID) -> None:
    await _safe_notify(
        {"type": "instance.status_changed", "id": str(instance_id)}
    )


async def publish_instance_destroyed(*, instance_id: UUID) -> None:
    await _safe_notify({"type": "instance.destroyed", "id": str(instance_id)})


async def publish_session_created(*, session_id: UUID) -> None:
    await _safe_notify({"type": "session.created", "id": str(session_id)})


async def publish_session_closed(
    *, session_id: UUID, status: str
) -> None:
    await _safe_notify(
        {"type": "session.closed", "id": str(session_id), "status": status}
    )


async def listen_events(
    conn: asyncpg.Connection,
) -> AsyncIterator[str]:
    """Async generator qui yield les payloads bruts (JSON string) reçus
    sur le channel `supervision_events` via la connexion asyncpg fournie.

    L'appelant gère l'add_listener / remove_listener et la durée de vie
    de la connexion.
    """
    queue: asyncio.Queue[str] = asyncio.Queue()

    def _on_notify(
        _conn: asyncpg.Connection,
        _pid: int,
        _channel: str,
        payload: str,
    ) -> None:
        queue.put_nowait(payload)

    await conn.add_listener(CHANNEL, _on_notify)
    try:
        while True:
            yield await queue.get()
    finally:
        await conn.remove_listener(CHANNEL, _on_notify)
