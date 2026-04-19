from __future__ import annotations

import asyncio
import json
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status

from agflow.auth.dependencies import require_admin
from agflow.schemas.infra import ScriptRunRequest, ServerCreate, ServerSummary, ServerUpdate
from agflow.services import (
    infra_certificates_service,
    infra_servers_service,
    ssh_executor,
)

_log = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/infra/servers",
    tags=["infra-servers"],
)

_admin = [Depends(require_admin)]


@router.get("/manifest", dependencies=_admin)
async def get_script_manifest(url: str):
    """Proxy-fetch a script manifest JSON from a remote URL."""
    import httpx

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url)
        if resp.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to fetch manifest: HTTP {resp.status_code}",
            )
        return resp.json()


@router.get("", response_model=list[ServerSummary], dependencies=_admin)
async def list_servers():
    return await infra_servers_service.list_all()


@router.post("", response_model=ServerSummary, status_code=status.HTTP_201_CREATED, dependencies=_admin)
async def create_server(payload: ServerCreate):
    return await infra_servers_service.create(
        name=payload.name,
        server_type=payload.type,
        host=payload.host,
        port=payload.port,
        username=payload.username,
        password=payload.password,
        certificate_id=payload.certificate_id,
    )


@router.get("/{server_id}", response_model=ServerSummary, dependencies=_admin)
async def get_server(server_id: UUID):
    try:
        return await infra_servers_service.get_by_id(server_id)
    except infra_servers_service.ServerNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{server_id}", response_model=ServerSummary, dependencies=_admin)
async def update_server(server_id: UUID, payload: ServerUpdate):
    try:
        return await infra_servers_service.update(server_id, **payload.model_dump(exclude_unset=True))
    except infra_servers_service.ServerNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{server_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=_admin)
async def delete_server(server_id: UUID):
    try:
        await infra_servers_service.delete(server_id)
    except infra_servers_service.ServerNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{server_id}/test-connection", dependencies=_admin)
async def test_connection(server_id: UUID):
    try:
        creds = await infra_servers_service.get_credentials(server_id)
    except infra_servers_service.ServerNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    private_key = None
    passphrase = None
    if creds.get("certificate_id"):
        cert = await infra_certificates_service.get_decrypted(creds["certificate_id"])
        private_key = cert.get("private_key")
        passphrase = cert.get("passphrase")

    return await ssh_executor.test_connection(
        host=creds["host"],
        port=creds["port"],
        username=creds["username"],
        password=creds["password"],
        private_key=private_key,
        passphrase=passphrase,
    )


@router.post("/{server_id}/run-script", dependencies=_admin)
async def run_script(server_id: UUID, payload: ScriptRunRequest):
    """Fetch a script manifest from URL, substitute args, execute via SSH."""
    import httpx

    # 1. Get server credentials
    try:
        creds = await infra_servers_service.get_credentials(server_id)
    except infra_servers_service.ServerNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    private_key = None
    passphrase = None
    if creds.get("certificate_id"):
        cert = await infra_certificates_service.get_decrypted(creds["certificate_id"])
        private_key = cert.get("private_key")
        passphrase = cert.get("passphrase")

    # 2. Fetch script manifest
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(payload.script_url)
        if resp.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to fetch script manifest: HTTP {resp.status_code}",
            )
        manifest = resp.json()

    command_template: str = manifest.get("command", "")
    if not command_template:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Script manifest has no command")

    # 3. Substitute {ARG} placeholders
    command = command_template
    for key, value in payload.args.items():
        command = command.replace(f"{{{key}}}", value)

    # 4. Execute via SSH
    try:
        result = await ssh_executor.exec_command(
            host=creds["host"],
            port=creds["port"],
            username=creds["username"],
            password=creds["password"],
            private_key=private_key,
            passphrase=passphrase,
            command=command,
        )
    except ssh_executor.SSHConnectionError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    return {
        "exit_code": result["exit_code"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "command": command,
    }


@router.websocket("/{server_id}/exec")
async def ws_exec(ws: WebSocket, server_id: UUID, token: str = ""):
    """WebSocket SSH execution with real-time stdout/stderr streaming.

    Auth via query param: ?token=JWT
    Client sends: {"command": "...", "script_url": "...", "args": {...}}
    Server streams: {"type": "stdout|stderr|exit|error|cmd", "data": "..."}
    """
    # Authenticate via query param (browsers can't send WS headers)
    from agflow.auth.jwt import InvalidTokenError, decode_token

    if not token:
        await ws.close(code=4001, reason="Missing token")
        return
    try:
        decode_token(token)
    except InvalidTokenError:
        await ws.close(code=4001, reason="Invalid token")
        return

    await ws.accept()

    try:
        # 1. Receive execution request
        raw = await ws.receive_text()
        payload = json.loads(raw)

        command = payload.get("command", "")
        script_url = payload.get("script_url")
        args = payload.get("args", {})

        # If script_url provided, fetch manifest and build command
        if script_url and not command:
            import httpx

            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(script_url)
                if resp.status_code != 200:
                    await ws.send_json({"type": "error", "data": f"Failed to fetch manifest: HTTP {resp.status_code}"})
                    await ws.close()
                    return
                manifest = resp.json()

            command = manifest.get("command", "")
            for key, value in args.items():
                command = command.replace(f"{{{key}}}", value)

        if not command:
            await ws.send_json({"type": "error", "data": "No command to execute"})
            await ws.close()
            return

        # Send the resolved command back
        await ws.send_json({"type": "cmd", "data": command})

        # 2. Get credentials
        creds = await infra_servers_service.get_credentials(server_id)

        private_key = None
        passphrase = None
        if creds.get("certificate_id"):
            cert = await infra_certificates_service.get_decrypted(creds["certificate_id"])
            private_key = cert.get("private_key")
            passphrase = cert.get("passphrase")

        # 3. Open SSH and stream
        import asyncssh

        conn_kwargs = {
            "host": creds["host"],
            "port": creds["port"],
            "known_hosts": None,
        }
        if creds.get("username"):
            conn_kwargs["username"] = creds["username"]
        if creds.get("password"):
            conn_kwargs["password"] = creds["password"]
        if private_key:
            key = asyncssh.import_private_key(private_key, passphrase)
            conn_kwargs["client_keys"] = [key]

        async with asyncssh.connect(**conn_kwargs) as conn:
            process = await conn.create_process(command, encoding="utf-8")

            async def read_stream(stream, stream_type: str):
                async for line in stream:
                    await ws.send_json({"type": stream_type, "data": line})

            stdout_task = asyncio.create_task(read_stream(process.stdout, "stdout"))
            stderr_task = asyncio.create_task(read_stream(process.stderr, "stderr"))

            await asyncio.gather(stdout_task, stderr_task)
            await process.wait()

            await ws.send_json({"type": "exit", "data": str(process.exit_status)})

    except WebSocketDisconnect:
        _log.info("ws_exec.client_disconnected", server_id=str(server_id))
    except Exception as exc:
        _log.error("ws_exec.error", server_id=str(server_id), error=str(exc))
        try:
            await ws.send_json({"type": "error", "data": str(exc)})
        except Exception:
            pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass
