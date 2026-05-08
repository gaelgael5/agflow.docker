"""Interactive terminal for Docker containers via aiodocker exec.

WebSocket → aiodocker exec -ti → /bin/sh inside the container.
No SSH dependency: uses the Docker socket already mounted in the backend container.
"""
from __future__ import annotations

import asyncio
import contextlib

import aiodocker
import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

_log = structlog.get_logger(__name__)


async def _resolve_to_container_id(maybe_id: str) -> str:
    """Résout un service Swarm vers son container_id. Retourne l'input tel quel si ce n'est pas un service."""
    docker = aiodocker.Docker()
    try:
        try:
            svc = await docker.services.inspect(maybe_id)
        except aiodocker.exceptions.DockerError as exc:
            if exc.status == 404:
                return maybe_id
            raise
        svc_name = (svc.get("Spec") or {}).get("Name", "")
        tasks = await docker.tasks.list(filters={"service": svc_name})
        for task in tasks or []:
            if (task.get("Status") or {}).get("State") == "running":
                cid = ((task.get("Status") or {}).get("ContainerStatus") or {}).get("ContainerID")
                if cid:
                    return cid
        raise ValueError(f"Service {maybe_id} has no running task")
    finally:
        await docker.close()


router = APIRouter(
    prefix="/api/admin",
    tags=["admin-terminal"],
)


@router.websocket("/containers/{container_id}/terminal")
async def container_terminal(ws: WebSocket, container_id: str) -> None:
    await ws.accept()

    docker = aiodocker.Docker()
    try:
        resolved_id = await _resolve_to_container_id(container_id)

        try:
            container = await docker.containers.get(resolved_id)
        except aiodocker.exceptions.DockerError as exc:
            if exc.status == 404:
                await ws.send_bytes(b"\r\n\x1b[31mContainer introuvable\x1b[0m\r\n")
                await ws.close(code=4004, reason="container not found")
                return
            raise

        info = await container.show()
        if not info.get("State", {}).get("Running", False):
            await ws.send_bytes(b"\r\n\x1b[31mLe container n'est pas en cours d'ex\xc3\xa9cution\x1b[0m\r\n")
            await ws.close(code=4009, reason="container not running")
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
            _log.info("terminal.open", container_id=resolved_id[:12])

            async def _read() -> None:
                try:
                    while True:
                        msg = await stream.read_out()
                        if msg is None:
                            break
                        await ws.send_bytes(msg.data)
                except (asyncio.CancelledError, WebSocketDisconnect):
                    pass
                except Exception as exc:
                    _log.warning("terminal.read_error", error=str(exc))

            async def _write() -> None:
                try:
                    while True:
                        data = await ws.receive_bytes()
                        await stream.write_in(data)
                except (WebSocketDisconnect, asyncio.CancelledError):
                    pass
                except Exception as exc:
                    _log.warning("terminal.write_error", error=str(exc))

            read_task = asyncio.create_task(_read())
            write_task = asyncio.create_task(_write())
            _, pending = await asyncio.wait(
                {read_task, write_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()

        _log.info("terminal.close", container_id=resolved_id[:12])

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        _log.error("terminal.error", error=str(exc))
        with contextlib.suppress(Exception):
            await ws.send_bytes(f"\r\n\x1b[31mErreur: {exc}\x1b[0m\r\n".encode())
        with contextlib.suppress(Exception):
            await ws.close(code=4500, reason="Internal error")
    finally:
        await docker.close()
