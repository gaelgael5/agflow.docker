"""Interactive terminal for Docker containers via SSH + docker exec.

Same approach as infra/servers shell: WebSocket → asyncssh → docker exec -ti.
Works for local containers (SSH to localhost) and remote containers (SSH to host).
"""
from __future__ import annotations

import asyncio
import contextlib

import asyncssh
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

    try:
        # SSH to the Docker host to run docker exec.
        # From inside the backend container, the host is at the Docker gateway.
        import os

        host = os.environ.get("DOCKER_HOST_SSH", "172.20.0.1")
        port = 22
        username = "root"
        key_path = "/app/.ssh/backend_key"

        conn_kwargs: dict = {
            "host": host,
            "port": port,
            "username": username,
            "known_hosts": None,
        }
        if os.path.exists(key_path):
            conn_kwargs["client_keys"] = [asyncssh.read_private_key(key_path)]

        async with asyncssh.connect(**conn_kwargs) as conn:
            command = f"docker exec -ti {container_id} /bin/sh"

            process = await conn.create_process(
                command,
                term_type="xterm-256color",
                term_size=(120, 40),
                encoding=None,
            )

            _log.info("terminal.open", container_id=container_id[:12], host=host)

            async def ssh_to_ws():
                try:
                    while True:
                        data = await process.stdout.read(4096)
                        if not data:
                            break
                        await ws.send_bytes(data)
                except (asyncio.CancelledError, WebSocketDisconnect):
                    pass
                except Exception as exc:
                    _log.warning("terminal.read_error", error=str(exc))

            async def ws_to_ssh():
                try:
                    while True:
                        data = await ws.receive_bytes()
                        process.stdin.write(data)
                except (WebSocketDisconnect, asyncio.CancelledError):
                    process.stdin.write_eof()
                except Exception as exc:
                    _log.warning("terminal.write_error", error=str(exc))

            async def ssh_stderr_to_ws():
                try:
                    while True:
                        data = await process.stderr.read(4096)
                        if not data:
                            break
                        await ws.send_bytes(data)
                except (asyncio.CancelledError, WebSocketDisconnect):
                    pass

            tasks = [
                asyncio.create_task(ssh_to_ws()),
                asyncio.create_task(ws_to_ssh()),
                asyncio.create_task(ssh_stderr_to_ws()),
            ]

            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()

        _log.info("terminal.close", container_id=container_id[:12])

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        _log.error("terminal.error", error=str(exc))
        with contextlib.suppress(Exception):
            await ws.send_bytes(f"\r\n\x1b[31mError: {exc}\x1b[0m\r\n".encode())
        with contextlib.suppress(Exception):
            await ws.close(code=4500, reason="Internal error")
