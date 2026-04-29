from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status

from agflow.auth.dependencies import require_operator as require_admin
from agflow.schemas.infra import (
    MachineCreate,
    MachineSummary,
    MachineUpdate,
    ScriptRunRequest,
)
from agflow.services import (
    infra_certificates_service,
    infra_machines_runs_service,
    infra_machines_service,
    infra_named_type_actions_service,
    infra_named_types_service,
    ssh_executor,
)

_log = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/api/infra/machines",
    tags=["infra-machines"],
)

_admin = [Depends(require_admin)]


# ── Script manifest proxy ────────────────────────────────

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


# ── CRUD ─────────────────────────────────────────────────

@router.get("", response_model=list[MachineSummary], dependencies=_admin)
async def list_machines():
    return await infra_machines_service.list_all()


@router.post("", response_model=MachineSummary, status_code=status.HTTP_201_CREATED, dependencies=_admin)
async def create_machine(payload: MachineCreate):
    created = await infra_machines_service.create(
        name=payload.name,
        type_id=payload.type_id,
        host=payload.host,
        port=payload.port,
        username=payload.username,
        password=payload.password,
        certificate_id=payload.certificate_id,
        parent_id=payload.parent_id,
        user_id=payload.user_id,
        environment=payload.environment,
    )
    return created


@router.get("/{machine_id}", response_model=MachineSummary, dependencies=_admin)
async def get_machine(machine_id: UUID):
    try:
        return await infra_machines_service.get_by_id(machine_id)
    except infra_machines_service.MachineNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{machine_id}", response_model=MachineSummary, dependencies=_admin)
async def update_machine(machine_id: UUID, payload: MachineUpdate):
    try:
        updated = await infra_machines_service.update(
            machine_id, **payload.model_dump(exclude_unset=True),
        )
    except infra_machines_service.MachineNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return updated


@router.delete("/{machine_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=_admin)
async def delete_machine(machine_id: UUID):
    try:
        await infra_machines_service.delete(machine_id)
    except infra_machines_service.MachineNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


# ── SSH helpers (test, containers, health) ───────────────

async def _get_ssh_creds(machine_id: UUID) -> tuple[dict[str, Any], str | None, str | None]:
    """Return (creds, private_key, passphrase) for SSH use. Raises MachineNotFoundError."""
    creds = await infra_machines_service.get_credentials(machine_id)
    private_key = None
    passphrase = None
    if creds.get("certificate_id"):
        cert = await infra_certificates_service.get_decrypted(creds["certificate_id"])
        private_key = cert.get("private_key")
        passphrase = cert.get("passphrase")
    return creds, private_key, passphrase


@router.post("/{machine_id}/test-connection", dependencies=_admin)
async def test_connection(machine_id: UUID):
    try:
        creds, private_key, passphrase = await _get_ssh_creds(machine_id)
    except infra_machines_service.MachineNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return await ssh_executor.test_connection(
        host=creds["host"],
        port=creds["port"],
        username=creds["username"],
        password=creds["password"],
        private_key=private_key,
        passphrase=passphrase,
    )


@router.get("/{machine_id}/containers", dependencies=_admin)
async def list_containers(machine_id: UUID):
    """List Docker containers running on this machine via SSH."""
    try:
        creds, private_key, passphrase = await _get_ssh_creds(machine_id)
    except infra_machines_service.MachineNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

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

    return {"containers": containers, "machine_id": str(machine_id)}


@router.get("/{machine_id}/health", dependencies=_admin)
async def health_check(machine_id: UUID):
    """Check machine health — auto-detects K3s (port 6443) or Docker (SSH)."""
    import httpx

    try:
        machine = await infra_machines_service.get_by_id(machine_id)
    except infra_machines_service.MachineNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    meta = machine.metadata or {}
    has_k3s = bool(meta.get("k3s_version"))
    has_docker = bool(meta.get("docker")) and meta.get("docker") != "non installe"

    state = "down"
    detail = ""
    status_code = 0

    if has_k3s:
        try:
            async with httpx.AsyncClient(verify=False, timeout=5) as client:
                resp = await client.get(f"https://{machine.host}:6443/healthz")
                code = resp.status_code
                detail = resp.text.strip()[:200]
                if code in (200, 401):
                    state = "healthy"
                elif code == 503:
                    state = "starting"
        except Exception as exc:
            detail = str(exc)

    elif has_docker:
        try:
            creds, private_key, passphrase = await _get_ssh_creds(machine_id)
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
        try:
            creds, private_key, passphrase = await _get_ssh_creds(machine_id)
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

    if state == "healthy" and machine.status != "initialized":
        await infra_machines_service.update_status(machine_id, "initialized")
    elif state in ("down", "starting", "ssh_ok") and machine.status == "initialized":
        await infra_machines_service.update_status(machine_id, "not_initialized")

    return {
        "healthy": healthy,
        "state": state,
        "status_code": status_code,
        "detail": detail,
        "machine_id": str(machine_id),
    }


# ── WebSocket SSH shell (xterm.js) ───────────────────────

@router.websocket("/{machine_id}/shell")
async def ws_shell(ws: WebSocket, machine_id: UUID, token: str = ""):
    """Interactive SSH shell via WebSocket + xterm.js.

    Auth via query param: ?token=JWT
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
        creds, private_key, passphrase = await _get_ssh_creds(machine_id)

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
                encoding=None,
            )

            async def ws_to_ssh():
                try:
                    while True:
                        data = await ws.receive_bytes()
                        process.stdin.write(data)
                except (WebSocketDisconnect, Exception):
                    process.stdin.write_eof()

            async def ssh_to_ws():
                try:
                    while True:
                        data = await process.stdout.read(4096)
                        if not data:
                            break
                        await ws.send_bytes(data)
                except Exception:
                    pass

            async def ssh_stderr_to_ws():
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

            _done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()

    except WebSocketDisconnect:
        _log.info("ws_shell.disconnected", machine_id=str(machine_id))
    except Exception as exc:
        _log.error("ws_shell.error", machine_id=str(machine_id), error=str(exc))
        try:
            await ws.send_bytes(f"\r\n\x1b[31mError: {exc}\x1b[0m\r\n".encode())
        except Exception:
            pass
    finally:
        try:
            await ws.close()
        except Exception:
            pass


# ── One-shot script run (HTTP) ───────────────────────────

@router.post("/{machine_id}/run-script", dependencies=_admin)
async def run_script(machine_id: UUID, payload: ScriptRunRequest):
    """Fetch a script manifest from URL, substitute args, execute via SSH."""
    import httpx

    try:
        creds, private_key, passphrase = await _get_ssh_creds(machine_id)
    except infra_machines_service.MachineNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

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

    command = command_template
    for key, value in payload.args.items():
        command = command.replace(f"{{{key}}}", value)

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


# ── Machine runs history ─────────────────────────────────

@router.get("/{machine_id}/runs", dependencies=_admin)
async def list_machine_runs(machine_id: UUID, limit: int = 50):
    return await infra_machines_runs_service.list_by_machine(machine_id, limit=limit)


# ── WebSocket exec (streaming + run tracking + auto-provision) ──

@router.websocket("/{machine_id}/exec")
async def ws_exec(ws: WebSocket, machine_id: UUID, token: str = ""):
    """WebSocket SSH execution with real-time stdout/stderr streaming.

    Auth via query param: ?token=JWT

    Initial client payload (JSON):
      - `action_id` UUID — id of an infra_named_type_actions row (URL looked up from DB).
      - `script_url` + optional `command` — fallback for ad-hoc scripts (no run tracking)
      - `args` dict — placeholders to substitute in the command

    Post-execution tag dispatch: if the fetched manifest carries a `tags` array,
    the last JSON line of stdout is parsed and passed to each tag's handler.
    Supported tags:
      - `add_node` : create a child machine (cert + machine row) using the parsed
        JSON info. The child's type_id is inherited from the parent machine's
        named_type.sub_type_id.

    Server streams {type, data} messages: stdout, stderr, exit, error, cmd, provisioned, status_changed.
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

    run_id: UUID | None = None
    triggered_action_name: str | None = None
    manifest_tags: list[str] = []

    try:
        raw = await ws.receive_text()
        payload = json.loads(raw)

        command = payload.get("command", "")
        script_url = payload.get("script_url")
        args = payload.get("args", {})
        action_id_raw = payload.get("action_id")

        # 1. Resolve script URL and action metadata
        if action_id_raw:
            action = await infra_named_type_actions_service.get_by_id(UUID(action_id_raw))
            script_url = action.url
            triggered_action_name = action.action_name
            run_row = await infra_machines_runs_service.start(machine_id, action.id)
            run_id = run_row.id

        # 2. Fetch manifest and substitute placeholders
        if script_url and not command:
            import httpx

            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(script_url)
                if resp.status_code != 200:
                    await ws.send_json({"type": "error", "data": f"Failed to fetch manifest: HTTP {resp.status_code}"})
                    if run_id:
                        await infra_machines_runs_service.finish(
                            run_id, success=False, error_message=f"Manifest HTTP {resp.status_code}",
                        )
                    await ws.close()
                    return
                manifest = resp.json()

            command = manifest.get("command", "")
            raw_tags = manifest.get("tags") or []
            if isinstance(raw_tags, list):
                manifest_tags = [str(t) for t in raw_tags]
            _log.info(
                "ws_exec.manifest_fetched",
                url=script_url,
                manifest_tags=manifest_tags,
                has_command=bool(command),
            )
            for key, value in args.items():
                command = command.replace(f"{{{key}}}", value)

        if not command:
            await ws.send_json({"type": "error", "data": "No command to execute"})
            if run_id:
                await infra_machines_runs_service.finish(
                    run_id, success=False, error_message="No command to execute",
                )
            await ws.close()
            return

        await ws.send_json({"type": "cmd", "data": command})

        # 3. SSH + stream
        creds, private_key, passphrase = await _get_ssh_creds(machine_id)

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

            success = exit_code == 0

            # 4. Post-execution semantic hooks
            _log.info(
                "ws_exec.post",
                success=success,
                manifest_tags=manifest_tags,
                triggered_action_name=triggered_action_name,
                stdout_lines_count=len(stdout_lines),
            )
            if success:
                # Tag dispatch — triggered by manifest.tags
                if manifest_tags:
                    output_json = _parse_last_json(stdout_lines)
                    _log.info(
                        "ws_exec.tag_dispatch_entering",
                        manifest_tags=manifest_tags,
                        parsed_ok=bool(output_json),
                    )
                    for tag in manifest_tags:
                        await _handle_tag(tag, ws, conn, machine_id, output_json)

                # Legacy behaviour: install action → mark machine as initialized
                if triggered_action_name == "install":
                    output_json = _parse_last_json(stdout_lines)
                    if output_json:
                        meta_update = {}
                        for k in ("k3s_version", "node_ready", "ip", "kubeconfig_b64"):
                            if output_json.get(k):
                                meta_update[k] = str(output_json[k])
                        if meta_update:
                            await infra_machines_service.merge_metadata(machine_id, meta_update)
                            await ws.send_json({
                                "type": "stdout",
                                "data": f"\n✓ Metadata sauvegardées: {', '.join(meta_update.keys())}\n",
                            })
                    await infra_machines_service.update_status(machine_id, "initialized")
                    await ws.send_json({"type": "stdout", "data": "✓ Status → initialized\n"})
                    await ws.send_json({"type": "status_changed", "data": "initialized"})

            # 5. Close the run row
            if run_id:
                await infra_machines_runs_service.finish(run_id, success=success, exit_code=exit_code)

    except WebSocketDisconnect:
        _log.info("ws_exec.client_disconnected", machine_id=str(machine_id))
        if run_id:
            await infra_machines_runs_service.finish(
                run_id, success=False, error_message="client disconnected",
            )
    except Exception as exc:
        _log.error("ws_exec.error", machine_id=str(machine_id), error=str(exc))
        if run_id:
            await infra_machines_runs_service.finish(
                run_id, success=False, error_message=str(exc),
            )
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


async def _handle_tag(
    tag: str,
    ws: WebSocket,
    conn,
    machine_id: UUID,
    output_json: dict | None,
) -> None:
    """Dispatch to the tag-specific handler."""
    if tag == "add_node":
        await _handle_add_node(ws, conn, machine_id, output_json)
    else:
        _log.info("tag.unknown", tag=tag)


async def _handle_add_node(
    ws: WebSocket,
    conn,  # asyncssh connection still open to the parent machine
    parent_machine_id: UUID,
    output_json: dict | None,
) -> None:
    """add_node tag : create child cert + machine from the parsed stdout JSON.

    The child machine's type_id is inherited from the parent machine's
    named_type.sub_type_id. Refuses to create if the parent has no sub_type
    (respects the "no programmatic modification of infra_types" rule).
    """
    if not output_json or output_json.get("status") != "ok":
        _log.info("add_node.no_json_output")
        return

    ip = output_json.get("ip", "")
    user = output_json.get("user", "")
    password = output_json.get("password", "")
    ssh_key_path = output_json.get("ssh_key", "")
    ctid = output_json.get("ctid", "")

    if not ip:
        _log.warning("add_node.no_ip")
        return

    await ws.send_json({"type": "stdout", "data": "\n── add_node ──\n"})

    # 1. Find parent's named_type. sub_type_id points directly to the child's
    # named_type variant (self-reference) — use it as the child machine's type_id.
    parent_machine = await infra_machines_service.get_by_id(parent_machine_id)
    parent_named_type = await infra_named_types_service.get_by_id(parent_machine.type_id)
    if not parent_named_type.sub_type_id:
        msg = f"La variante '{parent_named_type.name}' n'a pas de sous-type configuré"
        await ws.send_json({"type": "stderr", "data": f"✗ {msg}\n"})
        _log.warning("add_node.no_sub_type", parent_named_type_id=str(parent_named_type.id))
        return
    child_type_id = parent_named_type.sub_type_id

    # 2. Read the SSH private key from the parent machine
    cert_summary = None
    if ssh_key_path:
        try:
            result = await conn.run(f"cat {ssh_key_path}", check=True, encoding="utf-8")
            priv_key_content = result.stdout.strip()

            result_pub = await conn.run(f"cat {ssh_key_path}.pub", check=False, encoding="utf-8")
            pub_key_content = result_pub.stdout.strip() if result_pub.exit_status == 0 else None

            key_type = "ed25519" if "ed25519" in priv_key_content.lower() else "rsa"

            cert_name = f"lxc-{ctid}-{user}" if ctid else f"{ip}-{user}"
            cert_summary = await infra_certificates_service.create(
                name=cert_name,
                private_key=priv_key_content,
                public_key=pub_key_content,
                key_type=key_type,
            )
            await ws.send_json({"type": "stdout", "data": f"✓ Certificat SSH créé: {cert_name} ({key_type})\n"})
            _log.info("add_node.cert_created", name=cert_name, key_type=key_type)
        except Exception as exc:
            await ws.send_json({"type": "stderr", "data": f"✗ Lecture clé SSH échouée: {exc}\n"})
            _log.warning("add_node.key_read_failed", path=ssh_key_path, error=str(exc))

    # 3. Create the child machine
    try:
        machine_name = f"LXC-{ctid}" if ctid else ip

        meta = {}
        for k in ("distro", "ip_type", "docker", "ctid"):
            if output_json.get(k):
                meta[k] = str(output_json[k])

        new_machine = await infra_machines_service.create(
            name=machine_name,
            type_id=child_type_id,
            host=ip,
            port=22,
            username=user or None,
            password=password or None,
            certificate_id=cert_summary.id if cert_summary else None,
            metadata=meta,
            parent_id=parent_machine_id,
        )
        await ws.send_json({"type": "stdout", "data": f"✓ Machine créée: {machine_name} ({ip}:22, user={user})\n"})
        await ws.send_json({
            "type": "provisioned",
            "data": json.dumps({
                "machine_id": str(new_machine.id),
                "certificate_id": str(cert_summary.id) if cert_summary else None,
                "name": machine_name,
                "host": ip,
                "user": user,
            }),
        })
        _log.info(
            "add_node.machine_created",
            name=machine_name, host=ip, type_id=str(child_type_id),
        )
    except Exception as exc:
        await ws.send_json({"type": "stderr", "data": f"✗ Création machine échouée: {exc}\n"})
        _log.error("add_node.machine_create_failed", error=str(exc))
