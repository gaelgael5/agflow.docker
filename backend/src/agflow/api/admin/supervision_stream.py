"""WebSocket endpoint pour le push temps-réel des événements de supervision.

Auth : JWT en query param `?token=<jwt>`, rôle admin requis.
Channel : `supervision_events` (cf. supervision_events.py).
"""
from __future__ import annotations

import asyncio
from uuid import uuid4

import structlog
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from agflow.auth.dependencies import _extract_role
from agflow.auth.jwt import InvalidTokenError, decode_token
from agflow.db.pool import get_pool
from agflow.services import supervision_events

_log = structlog.get_logger(__name__)

router = APIRouter(tags=["admin-supervision"])


def _require_admin_from_token(token: str) -> str | None:
    """Retourne l'email admin ou None si token invalide/non-admin."""
    try:
        payload = decode_token(token)
    except InvalidTokenError:
        return None
    if _extract_role(payload) != "admin":
        return None
    sub = payload.get("sub", "")
    return sub or None


@router.websocket("/api/admin/supervision/stream")
async def supervision_stream(
    websocket: WebSocket,
    token: str = Query(default=""),
) -> None:
    admin_email = _require_admin_from_token(token)
    if not admin_email:
        # Avant accept() : on close avec un code custom 4401 (4xxx = app-defined)
        await websocket.close(code=4401)
        return

    await websocket.accept()
    connection_id = uuid4().hex[:8]
    _log.info(
        "supervision_stream.connected",
        connection_id=connection_id,
        admin=admin_email,
    )

    pool = await get_pool()
    try:
        async with pool.acquire() as conn:
            try:
                async for payload in supervision_events.listen_events(conn):
                    await websocket.send_text(payload)
            except WebSocketDisconnect:
                _log.info(
                    "supervision_stream.client_disconnect",
                    connection_id=connection_id,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                _log.exception(
                    "supervision_stream.error",
                    connection_id=connection_id,
                    error=str(exc),
                )
    finally:
        _log.info(
            "supervision_stream.disconnected", connection_id=connection_id
        )
