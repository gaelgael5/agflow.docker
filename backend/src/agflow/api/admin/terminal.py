from __future__ import annotations

import asyncio
import contextlib

import aiodocker
import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

_log = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/admin",
    tags=["admin-terminal"],
)


@router.websocket("/containers/{container_id}/terminal")
async def container_terminal(ws: WebSocket, container_id: str) -> None:
    await ws.accept()

    docker = aiodocker.Docker()
    try:
        try:
            container = await docker.containers.get(container_id)
        except aiodocker.exceptions.DockerError as exc:
            if exc.status == 404:
                await ws.close(code=4004, reason="Container not found")
                return
            raise

        info = await container.show()
        if not info.get("State", {}).get("Running", False):
            await ws.close(code=4009, reason="Container not running")
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
                "terminal.open",
                container_id=container_id[:12],
                container_name=(info.get("Name") or "").lstrip("/"),
            )

            async def _read_exec() -> None:
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

            async def _write_exec() -> None:
                try:
                    while True:
                        data = await ws.receive_bytes()
                        await stream.write_in(data)
                except (WebSocketDisconnect, asyncio.CancelledError):
                    pass
                except Exception as exc:
                    _log.warning("terminal.write_error", error=str(exc))

            read_task = asyncio.create_task(_read_exec())
            write_task = asyncio.create_task(_write_exec())

            try:
                done, pending = await asyncio.wait(
                    {read_task, write_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()
                for t in done:
                    if t.exception() is not None:
                        _log.warning("terminal.task_error", error=str(t.exception()))
            except Exception:
                read_task.cancel()
                write_task.cancel()

        _log.info("terminal.close", container_id=container_id[:12])

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        _log.error("terminal.error", error=str(exc))
        with contextlib.suppress(Exception):
            await ws.close(code=4500, reason="Internal error")
    finally:
        await docker.close()
