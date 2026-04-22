from __future__ import annotations

import asyncio
import json
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status

from agflow.auth.dependencies import require_operator as require_admin
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


@router.get("/{server_id}/containers", dependencies=_admin)
async def list_containers(server_id: UUID):
    """List Docker containers running on this server via SSH."""
    try:
        server = await infra_servers_service.get_by_id(server_id)
    except infra_servers_service.ServerNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    creds = await infra_servers_service.get_credentials(server_id)
    private_key = None
    passphrase = None
    if creds.get("certificate_id"):
        cert = await infra_certificates_service.get_decrypted(creds["certificate_id"])
        private_key = cert.get("private_key")
        passphrase = cert.get("passphrase")

    try:
        result = await ssh_executor.exec_command(
            host=creds["host"], port=creds["port"],
            username=creds["username"], password=creds["password"],
            private_key=private_key, passphrase=passphrase,
            command='sudo docker ps -a --format \'{"id":"{{.ID}}","name":"{{.Names}}","image":"{{.Image}}","status":"{{.Status}}","state":"{{.State}}","ports":"{{.Ports}}"}\'',
        )
    except ssh_executor.SSHConnectionError as exc:
        return {"containers": [], "error": str(exc)}

    containers = []
    for line in (result.get("stdout") or "").strip().split("\n"):
        line = line.strip()
        if line.startswith("{"):
            try:
                containers.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    return {"containers": containers, "server_id": str(server_id)}


@router.get("/{server_id}/health", dependencies=_admin)
async def health_check(server_id: UUID):
    """Check server health — auto-detects K3s (port 6443) or Docker (SSH)."""
    import httpx

    try:
        server = await infra_servers_service.get_by_id(server_id)
    except infra_servers_service.ServerNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    meta = server.metadata or {}
    has_k3s = bool(meta.get("k3s_version"))
    has_docker = bool(meta.get("docker")) and meta.get("docker") != "non installe"

    state = "down"
    detail = ""
    status_code = 0

    if has_k3s:
        # K3s: check HTTPS API port 6443
        try:
            async with httpx.AsyncClient(verify=False, timeout=5) as client:
                resp = await client.get(f"https://{server.host}:6443/healthz")
                code = resp.status_code
                detail = resp.text.strip()[:200]
                if code in (200, 401):
                    state = "healthy"
                elif code == 503:
                    state = "starting"
        except Exception as exc:
            detail = str(exc)

    elif has_docker:
        # Docker: SSH + docker info
        try:
            creds = await infra_servers_service.get_credentials(server_id)
            private_key = None
            passphrase = None
            if creds.get("certificate_id"):
                cert = await infra_certificates_service.get_decrypted(creds["certificate_id"])
                private_key = cert.get("private_key")
                passphrase = cert.get("passphrase")

            result = await ssh_executor.exec_command(
                host=creds["host"], port=creds["port"],
                username=creds["username"], password=creds["password"],
                private_key=private_key, passphrase=passphrase,
                command="docker info --format '{{.ServerVersion}}' 2>/dev/null || echo FAIL",
            )
            stdout = (result.get("stdout") or "").strip()
            if stdout and stdout != "FAIL" and result.get("exit_code") == 0:
                state = "healthy"
                detail = f"Docker {stdout}"
            else:
                detail = stdout or "docker info failed"
        except Exception as exc:
            detail = str(exc)

    else:
        # No K3s or Docker metadata — SSH only (no service installed yet)
        try:
            creds = await infra_servers_service.get_credentials(server_id)
            private_key = None
            passphrase = None
            if creds.get("certificate_id"):
                cert = await infra_certificates_service.get_decrypted(creds["certificate_id"])
                private_key = cert.get("private_key")
                passphrase = cert.get("passphrase")

            result = await ssh_executor.test_connection(
                host=creds["host"], port=creds["port"],
                username=creds["username"], password=creds["password"],
                private_key=private_key, passphrase=passphrase,
            )
            state = "ssh_ok" if result.get("success") else "down"
            detail = result.get("message", "")
        except Exception as exc:
            detail = str(exc)

    healthy = state == "healthy"

    # Sync DB status — only for K3s/Docker checks, not SSH-only
    if state in ("healthy",) and server.status != "initialized":
        await infra_servers_service.update_status(server_id, "initialized")
    elif state in ("down", "starting", "ssh_ok") and server.status == "initialized":
        await infra_servers_service.update_status(server_id, "not_initialized")

    return {"healthy": healthy, "state": state, "status_code": status_code, "detail": detail, "server_id": str(server_id)}


@router.websocket("/{server_id}/shell")
async def ws_shell(ws: WebSocket, server_id: UUID, token: str = ""):
    """Interactive SSH shell via WebSocket + xterm.js.

    Auth via query param: ?token=JWT
    Bidirectional: client sends keystrokes, server sends terminal output.
    """
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
        creds = await infra_servers_service.get_credentials(server_id)

        private_key = None
        passphrase = None
        if creds.get("certificate_id"):
            cert = await infra_certificates_service.get_decrypted(creds["certificate_id"])
            private_key = cert.get("private_key")
            passphrase = cert.get("passphrase")

        import asyncssh

        conn_kwargs: dict = {
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
            process = await conn.create_process(
                term_type="xterm-256color",
                term_size=(120, 40),
                encoding=None,  # binary mode for raw terminal
            )

            async def ws_to_ssh():
                """Forward client keystrokes to SSH stdin."""
                try:
                    while True:
                        data = await ws.receive_bytes()
                        process.stdin.write(data)
                except (WebSocketDisconnect, Exception):
                    process.stdin.write_eof()

            async def ssh_to_ws():
                """Forward SSH stdout to client."""
                try:
                    while True:
                        data = await process.stdout.read(4096)
                        if not data:
                            break
                        await ws.send_bytes(data)
                except Exception:
                    pass

            async def ssh_stderr_to_ws():
                """Forward SSH stderr to client."""
                try:
                    while True:
                        data = await process.stderr.read(4096)
                        if not data:
                            break
                        await ws.send_bytes(data)
                except Exception:
                    pass

            tasks = [
                asyncio.create_task(ws_to_ssh()),
                asyncio.create_task(ssh_to_ws()),
                asyncio.create_task(ssh_stderr_to_ws()),
            ]

            # Wait for any task to finish (disconnect or process exit)
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()

    except WebSocketDisconnect:
        _log.info("ws_shell.disconnected", server_id=str(server_id))
    except Exception as exc:
        _log.error("ws_shell.error", server_id=str(server_id), error=str(exc))
        try:
            await ws.send_bytes(f"\r\n\x1b[31mError: {exc}\x1b[0m\r\n".encode())
        except Exception:
            pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass


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
    Client sends: {"command":"...", "script_url":"...", "args":{...}, "action":"create|destroy"}
    Server streams: {"type": "stdout|stderr|exit|error|cmd|provisioned", "data": "..."}

    Post-execution: if action=create and exit=0, parses the last JSON line from stdout,
    reads the SSH key from the server, and auto-creates a certificate + server entry.
    """
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
        raw = await ws.receive_text()
        payload = json.loads(raw)

        command = payload.get("command", "")
        script_url = payload.get("script_url")
        args = payload.get("args", {})
        action = payload.get("action", "")

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

        await ws.send_json({"type": "cmd", "data": command})

        # Get credentials for the parent server
        creds = await infra_servers_service.get_credentials(server_id)

        private_key = None
        passphrase = None
        if creds.get("certificate_id"):
            cert = await infra_certificates_service.get_decrypted(creds["certificate_id"])
            private_key = cert.get("private_key")
            passphrase = cert.get("passphrase")

        import asyncssh

        conn_kwargs: dict = {
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

        stdout_lines: list[str] = []

        async with asyncssh.connect(**conn_kwargs) as conn:
            process = await conn.create_process(command, encoding="utf-8")

            async def read_stream(stream, stream_type: str):
                async for line in stream:
                    if stream_type == "stdout":
                        stdout_lines.append(line)
                    await ws.send_json({"type": stream_type, "data": line})

            stdout_task = asyncio.create_task(read_stream(process.stdout, "stdout"))
            stderr_task = asyncio.create_task(read_stream(process.stderr, "stderr"))

            await asyncio.gather(stdout_task, stderr_task)
            await process.wait()

            exit_code = process.exit_status or 0
            await ws.send_json({"type": "exit", "data": str(exit_code)})

            # ── Post-execution hooks ──
            if action == "create" and exit_code == 0:
                await _auto_provision(
                    ws, conn, server_id, stdout_lines, creds,
                )
            elif action == "install" and exit_code == 0:
                # Parse JSON output and store in metadata
                output_json = _parse_last_json(stdout_lines)
                if output_json:
                    meta_update = {}
                    for k in ("k3s_version", "node_ready", "ip", "kubeconfig_b64"):
                        if output_json.get(k):
                            meta_update[k] = str(output_json[k])
                    if meta_update:
                        await _merge_metadata(server_id, meta_update)
                        await ws.send_json({"type": "stdout", "data": f"\n✓ Metadata sauvegardées: {', '.join(meta_update.keys())}\n"})

                await infra_servers_service.update_status(server_id, "initialized")
                await ws.send_json({"type": "stdout", "data": "✓ Status → initialized\n"})
                await ws.send_json({"type": "status_changed", "data": "initialized"})

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


def _parse_last_json(stdout_lines: list[str]) -> dict | None:
    """Find and parse the last JSON line from script stdout."""
    for line in reversed(stdout_lines):
        stripped = line.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                continue
    return None


async def _merge_metadata(server_id: UUID, updates: dict) -> None:
    """Merge new keys into the server's existing metadata JSONB."""
    from agflow.db.pool import fetch_one as _fetch_one

    row = await _fetch_one(
        "UPDATE infra_servers SET metadata = metadata || $2::jsonb WHERE id = $1 RETURNING id",
        server_id, json.dumps(updates),
    )
    if row:
        _log.info("merge_metadata", server_id=str(server_id), keys=list(updates.keys()))


async def _auto_provision(
    ws: WebSocket,
    conn,  # asyncssh connection still open to the parent server
    parent_server_id: UUID,
    stdout_lines: list[str],
    parent_creds: dict,
) -> None:
    """Parse the last JSON line from script output and auto-create cert + server."""
    output_json = _parse_last_json(stdout_lines)

    if not output_json or output_json.get("status") != "ok":
        _log.info("auto_provision.no_json_output")
        return

    ip = output_json.get("ip", "")
    user = output_json.get("user", "")
    password = output_json.get("password", "")
    ssh_key_path = output_json.get("ssh_key", "")
    ctid = output_json.get("ctid", "")

    if not ip:
        _log.warning("auto_provision.no_ip")
        return

    await ws.send_json({"type": "stdout", "data": f"\n── Auto-provisioning ──\n"})

    # 1. Read the SSH private key from the parent server
    cert_summary = None
    if ssh_key_path:
        try:
            result = await conn.run(f"cat {ssh_key_path}", check=True, encoding="utf-8")
            priv_key_content = result.stdout.strip()

            # Also read public key
            result_pub = await conn.run(f"cat {ssh_key_path}.pub", check=False, encoding="utf-8")
            pub_key_content = result_pub.stdout.strip() if result_pub.exit_status == 0 else None

            # Detect key type
            key_type = "ed25519" if "ed25519" in priv_key_content.lower() else "rsa"

            cert_name = f"lxc-{ctid}-{user}" if ctid else f"{ip}-{user}"
            cert_summary = await infra_certificates_service.create(
                name=cert_name,
                private_key=priv_key_content,
                public_key=pub_key_content,
                key_type=key_type,
            )
            await ws.send_json({"type": "stdout", "data": f"✓ Certificat SSH créé: {cert_name} ({key_type})\n"})
            _log.info("auto_provision.cert_created", name=cert_name, key_type=key_type)
        except Exception as exc:
            await ws.send_json({"type": "stderr", "data": f"✗ Lecture clé SSH échouée: {exc}\n"})
            _log.warning("auto_provision.key_read_failed", path=ssh_key_path, error=str(exc))

    # 2. Create the new server entry
    try:
        # Get the parent server type to find the service type
        parent_server = await infra_servers_service.get_by_id(parent_server_id)
        from agflow.services import types_loader

        platform = types_loader.get_platform(parent_server.type)
        child_type = platform.service if platform else parent_server.type

        # Ensure the child type exists in infra_types
        from agflow.db.pool import execute

        await execute(
            "INSERT INTO infra_types (name, type) VALUES ($1, 'service') ON CONFLICT DO NOTHING",
            child_type,
        )

        server_name = f"LXC-{ctid}" if ctid else ip

        # Build metadata from script output
        meta = {}
        for k in ("distro", "ip_type", "docker", "ctid"):
            if output_json.get(k):
                meta[k] = str(output_json[k])

        new_server = await infra_servers_service.create(
            name=server_name,
            server_type=child_type,
            host=ip,
            port=22,
            username=user or None,
            password=password or None,
            certificate_id=cert_summary.id if cert_summary else None,
            metadata=meta,
            parent_id=parent_server_id,
        )
        await ws.send_json({"type": "stdout", "data": f"✓ Serveur créé: {server_name} ({ip}:22, user={user})\n"})
        await ws.send_json({
            "type": "provisioned",
            "data": json.dumps({
                "server_id": str(new_server.id),
                "certificate_id": str(cert_summary.id) if cert_summary else None,
                "name": server_name,
                "host": ip,
                "user": user,
            }),
        })
        _log.info("auto_provision.server_created", name=server_name, host=ip, type=child_type)
    except Exception as exc:
        await ws.send_json({"type": "stderr", "data": f"✗ Création serveur échouée: {exc}\n"})
        _log.error("auto_provision.server_create_failed", error=str(exc))
