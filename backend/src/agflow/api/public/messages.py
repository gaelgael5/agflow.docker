from __future__ import annotations

import asyncio
import contextlib
import os
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import aiodocker as _aiodocker
import structlog
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel

from agflow.auth.api_key import require_api_key
from agflow.auth.context import AuthContext
from agflow.db.pool import fetch_all, get_pool
from agflow.mom.consumers.ws_push import WsPushConsumer
from agflow.mom.envelope import Direction, Kind, Route
from agflow.mom.publisher import MomPublisher
from agflow.services import (
    agent_messages_service,
    agents_instances_service,
    sessions_service,
)

_log = structlog.get_logger(__name__)

router = APIRouter()

_GROUPS_CONFIG = {
    Direction.IN: ["dispatcher"],
    Direction.OUT: ["ws_push", "router"],
}


class MessageIn(BaseModel):
    kind: Kind = Kind.INSTRUCTION
    payload: dict[str, Any]
    route_to: str | None = None


async def _assert_session_owned(
    session_id: UUID,
    ctx: AuthContext,
) -> None:
    session = await sessions_service.get(
        session_id=session_id,
        api_key_id=ctx.api_key_id,
        is_admin=ctx.is_admin,
    )
    if session is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "session not found")
    if session["status"] != "active":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"session is {session['status']}",
        )


async def _assert_instance_alive(
    session_id: UUID,
    instance_id: UUID,
) -> None:
    rows = await fetch_all(
        "SELECT id FROM agents_instances "
        "WHERE id = $1 AND session_id = $2 AND destroyed_at IS NULL",
        instance_id,
        session_id,
    )
    if not rows:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "instance not found or destroyed",
        )


@router.post(
    "/api/v1/sessions/{session_id}/agents/{instance_id}/message",
    status_code=status.HTTP_201_CREATED,
)
async def post_message(
    session_id: UUID,
    instance_id: UUID,
    body: MessageIn,
    api_key: dict = require_api_key(),  # noqa: B008
) -> dict[str, str]:
    ctx = AuthContext.from_api_key(api_key)
    await _assert_session_owned(session_id, ctx)
    await _assert_instance_alive(session_id, instance_id)

    pool = await get_pool()
    publisher = MomPublisher(pool=pool, groups_config=_GROUPS_CONFIG)
    route = Route(target=body.route_to) if body.route_to else None
    msg_id = await publisher.publish(
        session_id=str(session_id),
        instance_id=str(instance_id),
        direction=Direction.IN,
        source=f"api_key:{ctx.api_key_id}",
        kind=body.kind,
        payload=body.payload,
        route=route,
    )
    return {"msg_id": str(msg_id)}


@router.get("/api/v1/sessions/{session_id}/agents/{instance_id}/messages")
async def get_messages(
    session_id: UUID,
    instance_id: UUID,
    kind: str | None = None,
    direction: str | None = None,
    limit: int = 100,
    api_key: dict = require_api_key(),  # noqa: B008
) -> list[dict[str, Any]]:
    ctx = AuthContext.from_api_key(api_key)
    await _assert_session_owned(session_id, ctx)

    return await agent_messages_service.list_for_instance(
        session_id=session_id,
        instance_id=instance_id,
        kind=kind,
        direction=direction,
        limit=limit,
    )


@router.websocket("/api/v1/sessions/{session_id}/agents/{instance_id}/stream")
async def ws_agent_stream(
    websocket: WebSocket,
    session_id: UUID,
    instance_id: UUID,
) -> None:
    await websocket.accept()
    pool = await get_pool()
    connection_id = uuid4().hex[:8]
    ws_consumer = WsPushConsumer(
        pool=pool,
        instance_id=str(instance_id),
        connection_id=connection_id,
    )
    try:
        async for event in ws_consumer.iter_events():
            await websocket.send_json(event)
    except WebSocketDisconnect:
        _log.info("ws_agent_stream.disconnected", connection_id=connection_id)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        _log.exception("ws_agent_stream.error", error=str(exc))


@router.get(
    "/api/v1/sessions/{session_id}/agents/{instance_id}/logs",
    response_class=PlainTextResponse,
)
async def get_agent_logs(
    session_id: UUID,
    instance_id: UUID,
    limit: int = 500,
    api_key: dict = require_api_key(),  # noqa: B008
) -> str:
    ctx = AuthContext.from_api_key(api_key)
    await _assert_session_owned(session_id, ctx)

    rows = await fetch_all(
        """
        SELECT created_at, kind, payload
        FROM agent_messages
        WHERE session_id = $1 AND instance_id = $2 AND direction = 'out'
        ORDER BY created_at DESC
        LIMIT $3
        """,
        str(session_id),
        str(instance_id),
        limit,
    )
    rows.reverse()

    lines = []
    for r in rows:
        ts = r["created_at"].isoformat()
        kind = r["kind"]
        payload = r["payload"] if isinstance(r["payload"], dict) else {}
        text = payload.get("text") or payload.get("message") or ""
        if not text and payload:
            import json as _json

            text = _json.dumps(payload, ensure_ascii=False)
        lines.append(f"[{ts}] [{kind}] {text}")

    return "\n".join(lines)


def _workspace_root(agent_slug: str) -> Path:
    base = Path(os.environ.get("AGFLOW_DATA_DIR", "/app/data"))
    return (base / "agents" / agent_slug / "workspace").resolve()


def _safe_subpath(root: Path, user_path: str) -> Path:
    user_path = (user_path or "").lstrip("/")
    target = (root / user_path).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "path traversal detected",
        ) from exc
    return target


@router.get("/api/v1/sessions/{session_id}/agents/{instance_id}/files")
async def browse_files(
    session_id: UUID,
    instance_id: UUID,
    path: str = "",
    api_key: dict = require_api_key(),  # noqa: B008
):
    ctx = AuthContext.from_api_key(api_key)
    await _assert_session_owned(session_id, ctx)

    instance = await agents_instances_service.get(
        session_id=session_id,
        instance_id=instance_id,
    )
    if instance is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "instance not found")

    root = _workspace_root(instance["agent_id"])
    if not root.is_dir():
        return {"type": "missing", "path": str(root), "entries": []}

    target = _safe_subpath(root, path)

    if target.is_file():
        if target.stat().st_size > 1_000_000:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                "file too large (>1MB); use a different tool",
            )
        return FileResponse(
            path=str(target),
            media_type="application/octet-stream",
        )

    if target.is_dir():
        entries = []
        for child in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name)):
            stat = child.stat()
            entries.append(
                {
                    "name": child.name,
                    "type": "dir" if child.is_dir() else "file",
                    "size": stat.st_size if child.is_file() else None,
                    "modified": stat.st_mtime,
                }
            )
        return {
            "type": "dir",
            "path": str(target.relative_to(root)) or ".",
            "entries": entries,
        }

    raise HTTPException(status.HTTP_404_NOT_FOUND, "path not found")


@router.websocket("/api/v1/sessions/{session_id}/agents/{instance_id}/exec")
async def ws_agent_exec(
    websocket: WebSocket,
    session_id: UUID,
    instance_id: UUID,
) -> None:
    # V1 limitation: one-shot agents only have a container alive during message
    # processing. Callers must exec while the agent is busy or accept 4009.
    await websocket.accept()

    container_name = await agents_instances_service.get_last_container_name(
        instance_id,
    )
    if not container_name:
        await websocket.close(
            code=4009,
            reason="no running container for this instance",
        )
        return

    docker = _aiodocker.Docker()
    try:
        try:
            container = await docker.containers.get(container_name)
        except _aiodocker.exceptions.DockerError as exc:
            if exc.status == 404:
                await websocket.close(code=4004, reason="container not found")
                return
            raise

        info = await container.show()
        if not info.get("State", {}).get("Running", False):
            await websocket.close(code=4009, reason="container not running")
            return

        exec_inst = await container.exec(
            cmd=["/bin/sh"],
            stdin=True,
            stdout=True,
            stderr=True,
            tty=True,
        )
        stream = exec_inst.start()
        async with stream:
            _log.info(
                "exec.open",
                instance_id=str(instance_id),
                container=container_name,
            )

            async def _read_exec() -> None:
                try:
                    while True:
                        msg = await stream.read_out()
                        if msg is None:
                            break
                        await websocket.send_bytes(msg.data)
                except (asyncio.CancelledError, WebSocketDisconnect):
                    pass
                except Exception as exc:
                    _log.warning("exec.read_error", error=str(exc))

            async def _write_exec() -> None:
                try:
                    while True:
                        data = await websocket.receive_bytes()
                        await stream.write_in(data)
                except (WebSocketDisconnect, asyncio.CancelledError):
                    pass
                except Exception as exc:
                    _log.warning("exec.write_error", error=str(exc))

            read_task = asyncio.create_task(_read_exec())
            write_task = asyncio.create_task(_write_exec())
            try:
                _, pending = await asyncio.wait(
                    {read_task, write_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()
            except Exception:
                read_task.cancel()
                write_task.cancel()

        _log.info("exec.close", instance_id=str(instance_id))
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        _log.error("exec.error", error=str(exc))
        with contextlib.suppress(Exception):
            await websocket.close(code=4500, reason="internal error")
    finally:
        await docker.close()
